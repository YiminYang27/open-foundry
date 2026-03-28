"""Discussion workflow: main loop, phase transitions, signal handling."""

import signal
import sys
import termios
from pathlib import Path

from forge.agents import AgentService
from forge.models import ForumContext, Session
from forge.orchestrator import OrchestratorService
from forge.session_io import SessionManager
from forge.synthesis import SynthesisService
from forge.utils.logger import logger, BOLD, NC


_pause_requested = False


def _on_pause_signal(*_):
    global _pause_requested
    _pause_requested = True
    print()
    logger.info("Pause requested -- waiting for current turn to finish...")


class ForumWorkflow:
    """Orchestrates the full discussion pipeline."""

    def __init__(self, smgr: SessionManager, ctx: ForumContext,
                 orch_svc: OrchestratorService, agent_svc: AgentService,
                 synth_svc: SynthesisService) -> None:
        self._smgr = smgr
        self._ctx = ctx
        self._orch_svc = orch_svc
        self._agent_svc = agent_svc
        self._synth_svc = synth_svc

    def run(self, *, execute_after: bool = False,
            feedback: str | None = None,
            synthesize_only: bool = False,
            topic_path: Path,
            mission_source: str,
            state: dict | None = None) -> None:
        """Run the full discussion pipeline.

        Phases: [feedback inject] -> discussion loop -> finalize
                -> [execution_phase] -> synthesize -> review
        """
        session = self._smgr.session
        ctx = self._ctx
        llm = self._orch_svc._llm  # all services share the same llm

        def _save_state(status: str) -> None:
            self._smgr.update_state(status, ctx.agents, ctx.max_turns,
                                    llm.model, mission_source)

        # Handle completed session warnings (for resume without --feedback)
        if state and state.get("status") == "completed":
            if feedback:
                self._smgr.archive_outputs()
                logger.info("Injecting feedback and resuming discussion")
            elif not synthesize_only:
                synthesis_exists = (session.work_dir / "synthesis.md").exists()
                if not synthesis_exists:
                    logger.warn("Session already completed but synthesis.md is missing.")
                    logger.warn("Consider: --synthesize-only to re-run synthesis only.")
                else:
                    logger.warn("Session already completed (synthesis.md exists).")
                    logger.warn("Re-entering discussion loop will add turns beyond "
                         "original completion. Use --synthesize-only to re-run "
                         "synthesis only.")

        # Signal handlers
        def on_interrupt(*_):
            print()
            logger.warn(f"Interrupted at turn {session.utterances}")
            _save_state("interrupted")
            logger.info(f"Resume with: --resume {session.work_dir}")
            sys.exit(130)

        signal.signal(signal.SIGINT, on_interrupt)
        signal.signal(signal.SIGTERM, on_interrupt)
        if hasattr(signal, 'SIGQUIT'):
            signal.signal(signal.SIGQUIT, _on_pause_signal)
        if hasattr(signal, 'SIGUSR1'):
            signal.signal(signal.SIGUSR1, _on_pause_signal)

        # Banner
        title_line = session.transcript.read_text(encoding="utf-8").split("\n")[0]
        title = title_line.replace("# Discussion: ", "") if title_line.startswith("# Discussion: ") else "Discussion"
        print(f"\n{BOLD}=== Forum Discussion ==={NC}\n")
        logger.info(f"Topic:     {title}")
        logger.info(f"Agents:    {' '.join(a.name for a in ctx.agents)}")
        logger.info(f"Max turns: {ctx.max_turns}")
        logger.info(f"Model:     {llm.model}")
        logger.info(f"Output:    {session.work_dir}")
        if state:
            logger.info(f"Resuming from turn {session.utterances + 1}")
        if sys.stdout.isatty() and not llm.dry_run:
            logger.info(f"Pause:     Ctrl+\\\\ or touch {session.work_dir}/PAUSE")
        print()

        # Inject feedback before entering main loop
        if feedback:
            self._smgr.inject_operator_turn(feedback)
            _save_state("running")

        # Synthesize-only mode
        if synthesize_only:
            if not session.state_file.exists():
                logger.fatal(f"No state.json found in {session.work_dir} -- cannot run synthesize-only")
            logger.info(f"Synthesize-only mode: skipping discussion loop")
            logger.info(f"Session has {session.utterances} turns")

            closing_file = session.work_dir / "closing.md"
            if closing_file.exists():
                logger.info("closing.md exists, re-running synthesis only")
            else:
                logger.info("closing.md missing, running finalize + synthesis")
                self._orch_svc.finalize(ctx, "unknown (synthesize-only mode)")

            self._synth_svc.synthesize(ctx.topic_body)
            if not llm.dry_run:
                self._synth_svc.review()

            synthesis = session.work_dir / "synthesis.md"
            if synthesis.exists():
                _save_state("completed")
                logger.ok(f"Synthesis written to {synthesis}")
            else:
                logger.warn("Synthesis was not produced")
            return

        # -------------------------------------------------------------------
        # Main discussion loop
        # -------------------------------------------------------------------
        self._run_discussion_loop(
            _save_state=_save_state,
            execute_after=execute_after,
            topic_path=topic_path,
            mission_source=mission_source,
            llm=llm,
        )

    def _run_discussion_loop(self, *, _save_state, execute_after,
                              topic_path, mission_source, llm) -> None:
        session = self._smgr.session
        ctx = self._ctx
        agent_names_set = {a.name for a in ctx.agents}

        while session.utterances < ctx.max_turns:
            print(f"{BOLD}--- Orchestrator picking speaker "
                  f"(turn {session.utterances + 1}/{ctx.max_turns}) ---{NC}")

            pick_result = self._orch_svc.pick_speaker(ctx)
            self._smgr.append_orchestrator_turn(pick_result)

            speaker = pick_result.get("speaker", "FALLBACK")
            reasoning = pick_result.get("reasoning", "")
            action = pick_result.get("action", "speak")

            # Consensus?
            if speaker == "CONSENSUS":
                logger.ok(f"Consensus reached: {reasoning}")
                self._finalize_and_synthesize(
                    _save_state=_save_state,
                    consensus_status="yes",
                    execute_after=execute_after,
                    topic_path=topic_path,
                    mission_source=mission_source,
                    llm=llm,
                )
                print(f"\n{BOLD}=== Forum Complete "
                      f"(consensus at turn {session.utterances}) ==={NC}")
                logger.info(f"Transcript: {session.transcript}")
                synthesis = session.work_dir / "synthesis.md"
                if synthesis.exists():
                    logger.info(f"Synthesis: {synthesis}")
                return

            # Fallback to round-robin
            if speaker == "FALLBACK" or speaker not in agent_names_set:
                if speaker != "FALLBACK":
                    logger.warn(f"Orchestrator picked unknown agent '{speaker}', "
                         f"falling back to round-robin")
                else:
                    logger.warn("Orchestrator fallback -> round-robin")
                speaker = OrchestratorService.next_round_robin(ctx.agents, session.last_speaker)
                action = "speak"

            # Anti-loop guard
            if speaker == session.last_speaker:
                session.consecutive_count += 1
            else:
                session.consecutive_count = 1

            if session.consecutive_count >= 3:
                logger.warn(f"Agent {speaker} picked 3x in a row, forcing rotation")
                speaker = OrchestratorService.next_round_robin(ctx.agents, speaker)
                session.consecutive_count = 1

            action_label = f" (execute)" if action == "execute" else ""
            logger.speaker_line(speaker, f"{reasoning}{action_label}")

            # Find agent object
            agent = next((a for a in ctx.agents if a.name == speaker), ctx.agents[0])

            # Agent speaks or executes
            if action == "execute":
                response = self._agent_svc.execute(agent, ctx, pick_result)
            else:
                response = self._agent_svc.speak(agent, ctx)
            if not response:
                response = "[agent declined]"

            # Record turn
            self._smgr.append_agent_turn(speaker, response, action,
                                          task=pick_result if action == "execute" else None)
            session.utterances += 1
            session.last_speaker = speaker
            session.speakers_history.append(speaker)

            # Parse agent status signal
            if action == "speak" and response:
                session.agent_statuses[speaker] = AgentService.parse_status_signal(response)

            # Verify after execute actions (with retry loop)
            if action == "execute" and ctx.orch.verify_persona and not llm.dry_run:
                max_task_retries = 3
                for retry_attempt in range(max_task_retries):
                    attempt_label = (f"retry{retry_attempt}"
                                     if retry_attempt > 0 else "")
                    if retry_attempt > 0:
                        print(f"{BOLD}--- Verifying task"
                              f" (retry {retry_attempt}/{max_task_retries}) ---{NC}")
                    else:
                        print(f"{BOLD}--- Verifying task ---{NC}")
                    verification = self._orch_svc.verify_task(ctx, pick_result, response)
                    v_status = verification.get("status", "pass")
                    v_details = verification.get("details", "")

                    self._smgr.append_verification(
                        f"turn-{session.utterances}",
                        v_status, v_details,
                        attempt_label=attempt_label)

                    if v_status == "pass":
                        logger.ok(f"Task verified: {v_details[:100]}")
                        break

                    if retry_attempt < max_task_retries - 1:
                        logger.warn(f"Task failed verification (attempt "
                             f"{retry_attempt + 1}/{max_task_retries}): "
                             f"{v_details[:100]}")
                        retry_task = dict(pick_result)
                        retry_task["task"] = (pick_result.get("task", "")
                                              + f"\n\nPREVIOUS ATTEMPT FAILED: "
                                              + v_details)
                        response = self._agent_svc.execute(agent, ctx, retry_task)
                        self._smgr.append_retry_turn(speaker, response,
                                                      retry_attempt + 1, retry_task)
                    else:
                        logger.warn(f"Task failed after {max_task_retries} attempts: "
                             f"{v_details[:100]}")

            _save_state("running")

            logger.ok(f"Turn {session.utterances}/{ctx.max_turns} complete "
               f"({speaker}{action_label})")

            # Pause check
            if not llm.dry_run and self._check_pause() and sys.stdout.isatty():
                _save_state("paused")
                try:
                    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
                except (termios.error, OSError):
                    pass
                try:
                    print(f"\n{BOLD}--- Paused after turn "
                          f"{session.utterances}/{ctx.max_turns} ---{NC}")
                    msg = input("Type message to inject (Enter to resume): ").strip()
                except (EOFError, KeyboardInterrupt):
                    msg = ""
                if msg:
                    self._smgr.inject_operator_turn(msg)
                _save_state("running")

            print()

        # Max turns reached
        logger.warn(f"Max turns ({ctx.max_turns}) reached without consensus")
        self._finalize_and_synthesize(
            _save_state=_save_state,
            consensus_status="no (max turns reached)",
            execute_after=execute_after,
            topic_path=topic_path,
            mission_source=mission_source,
            llm=llm,
        )

        print(f"\n{BOLD}=== Forum Complete "
              f"({session.utterances} turns, no consensus) ==={NC}")
        logger.info(f"Transcript: {session.transcript}")
        synthesis = session.work_dir / "synthesis.md"
        if synthesis.exists():
            logger.info(f"Synthesis: {synthesis}")

    def _finalize_and_synthesize(self, *, _save_state, consensus_status,
                                  execute_after, topic_path,
                                  mission_source, llm) -> None:
        """Run the post-discussion pipeline: finalize -> execute -> synthesize -> review."""
        ctx = self._ctx
        _save_state("completed")
        self._orch_svc.finalize(ctx, consensus_status)
        if execute_after:
            self._orch_svc.run_execution_phase(ctx, self._agent_svc)
        self._synth_svc.synthesize(ctx.topic_body)
        if not llm.dry_run:
            self._synth_svc.review()

    def _check_pause(self) -> bool:
        """Return True if a pause has been requested via signal or PAUSE file."""
        global _pause_requested
        if _pause_requested:
            _pause_requested = False
            return True
        pause_file = self._smgr.session.work_dir / "PAUSE"
        if pause_file.exists():
            pause_file.unlink()
            logger.info("PAUSE file detected")
            return True
        return False
