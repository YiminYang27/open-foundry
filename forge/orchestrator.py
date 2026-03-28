"""Orchestrator-driven functions: speaker selection, verification, finalization, execution."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from forge.llm import ClaudeCLI
from forge.utils.parsers import extract_json
from forge.models import Agent, ForumContext, Orchestrator, Session
from forge.prompts import load_template
from forge.session_io import SessionManager
from forge.utils.logger import logger, BOLD, NC


class OrchestratorService:
    """Encapsulates orchestrator-driven operations: picking, verification, finalization, execution."""

    def __init__(self, llm: ClaudeCLI, smgr: SessionManager) -> None:
        self._llm = llm
        self._smgr = smgr

    @staticmethod
    def next_round_robin(agents: list[Agent], last_speaker: str) -> str:
        if not last_speaker:
            return agents[0].name
        for i, a in enumerate(agents):
            if a.name == last_speaker:
                return agents[(i + 1) % len(agents)].name
        return agents[0].name

    def pick_speaker(self, ctx: ForumContext) -> dict:
        session = self._smgr.session

        transcript_ctx = self._smgr.get_transcript_context(
            recent_turns=ctx.recent_window)

        # Build speaker statistics from history
        speaker_stats = ""
        if session.speakers_history:
            counts = Counter(session.speakers_history)
            stats_parts = [f"{name}: {count}" for name, count in counts.most_common()]
            speaker_stats = f"\nSPEAKER HISTORY ({session.utterances} turns):\n  {', '.join(stats_parts)}\n"

        # Build recent orchestrator decisions from log
        recent_decisions = ""
        if session.orch_log.exists():
            lines = session.orch_log.read_text(encoding="utf-8").strip().splitlines()
            recent = lines[-5:] if len(lines) > 5 else lines
            decision_parts = []
            start_turn = session.utterances - len(recent) + 1
            for i, line in enumerate(recent):
                try:
                    d = json.loads(line)
                    speaker = d.get("speaker", "?")
                    reasoning = d.get("reasoning", "")
                    action = d.get("action", "")
                    action_tag = f" [{action}]" if action and action != "speak" else ""
                    decision_parts.append(f"  T{start_turn + i}: {speaker}{action_tag} -- \"{reasoning}\"")
                except json.JSONDecodeError:
                    continue
            if decision_parts:
                recent_decisions = "\nRECENT DECISIONS:\n" + "\n".join(decision_parts) + "\n"

        # Execute action block (only when orchestrator supports verification)
        action_block = ""
        if ctx.orch.verify_persona:
            action_block = """
You may also assign implementation tasks. In that case, output:
{{"speaker": "<name>", "action": "execute", "task": "<specific implementation task>", "verify": "<verification command or criteria>", "reasoning": "<one sentence>"}}

Use "action": "execute" when the discussion has reached enough consensus on a
topic and it is time to implement. Use the default speak mode when agents need
to discuss, review, or debate."""

        # Build agent status signals summary
        agent_statuses = ""
        if session.agent_statuses:
            status_parts = []
            for name, status in session.agent_statuses.items():
                sig = status.get("signal", "NONE")
                if sig == "NEEDS_DATA":
                    status_parts.append(f"  {name}: NEEDS_DATA -- {status.get('item', '?')}")
                elif sig == "DISAGREE_WITH":
                    status_parts.append(f"  {name}: DISAGREE_WITH {status.get('agent', '?')} "
                                        f"on {status.get('topic', '?')}")
                elif sig != "NONE":
                    status_parts.append(f"  {name}: {sig}")
            if status_parts:
                agent_statuses = ("\nAGENT STATUS SIGNALS:\n"
                                  + "\n".join(status_parts) + "\n")

        prompt = load_template("orchestrator_pick",
                               agent_list_str=ctx.agent_list_str,
                               pick_persona=ctx.orch.pick_persona,
                               turn_number=session.utterances + 1,
                               max_turns=ctx.max_turns,
                               speaker_stats=speaker_stats,
                               recent_decisions=recent_decisions,
                               agent_statuses=agent_statuses,
                               transcript_ctx=transcript_ctx,
                               action_block=action_block)

        raw = self._llm.complete(prompt, label="Orchestrator", timeout=120)
        if not raw:
            if self._llm.dry_run:
                return {"speaker": ctx.agents[0].name, "reasoning": "dry run"}
            logger.warn("Orchestrator returned empty response")
            return {"speaker": "FALLBACK", "reasoning": "orchestrator failed"}

        parsed = extract_json(raw)

        # Log decision
        with session.orch_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(parsed) + "\n")

        return parsed

    def verify_task(self, ctx: ForumContext, task: dict,
                    agent_response: str) -> dict:
        """Verify a completed task using the orchestrator's verification persona."""
        orch = ctx.orch

        if not orch.verify_persona:
            return {"status": "pass", "details": "no verification configured"}

        task_desc = task.get("task", "")
        verify_criteria = task.get("verify", "")

        prompt = load_template("verify_task",
                               verify_persona=orch.verify_persona,
                               task_desc=task_desc,
                               agent_response=agent_response,
                               verify_criteria=(verify_criteria or
                                   "(none specified -- check based on task description)"))

        raw = self._llm.complete(prompt, label="Verification", timeout=300)
        if not raw:
            return {"status": "pass",
                    "details": "dry run" if self._llm.dry_run else "verification call failed, assuming pass"}

        return extract_json(raw)

    def finalize(self, ctx: ForumContext, consensus_status: str) -> None:
        session = self._smgr.session

        transcript_content = session.transcript.read_text(encoding="utf-8")

        # Speaker breakdown
        counts: dict[str, int] = Counter()
        for line in transcript_content.splitlines():
            if line.startswith("### Turn "):
                parts = line.split(" -- ")
                if len(parts) >= 2:
                    counts[parts[1].split()[0].strip()] += 1

        breakdown = "\n".join(f"- {name}: {count} turns"
                              for name, count in sorted(counts.items()))

        truncated = self._smgr.truncate_transcript_for_closing()

        summary_prompt = load_template("finalize",
                                        close_persona=ctx.orch.close_persona,
                                        truncated=truncated)

        summary = self._llm.complete(summary_prompt, label="Closing summary")
        if not summary:
            summary = ("[dry run closing summary]" if self._llm.dry_run
                       else "[failed to generate closing summary]")

        closing_file = session.work_dir / "closing.md"
        closing_file.write_text(
            f"# Closing Summary\n\n"
            f"{summary}\n\n"
            f"## Statistics\n\n"
            f"- Total turns: {session.utterances}\n"
            f"- Speaker breakdown:\n{breakdown}\n"
            f"- Consensus: {consensus_status}\n"
            f"- Model: {self._llm.model}\n"
            f"- Completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
            encoding="utf-8",
        )

        logger.ok(f"Closing summary written to {closing_file}")

    def run_execution_phase(self, ctx: ForumContext, agent_svc) -> None:
        """Decompose closing summary into tasks and execute them."""
        session = self._smgr.session

        closing_file = session.work_dir / "closing.md"
        if not closing_file.exists():
            logger.warn("No closing.md found, skipping execution phase")
            return

        if not ctx.orch.verify_persona:
            logger.warn("Orchestrator has no verification persona, skipping execution phase")
            return

        print(f"\n{BOLD}--- Post-Discussion Execution Phase ---{NC}")

        closing_summary = closing_file.read_text(encoding="utf-8")
        prompt = load_template("task_decompose",
                               verify_persona=ctx.orch.verify_persona,
                               closing_summary=closing_summary,
                               agent_list_str=ctx.agent_list_str)

        raw = self._llm.complete(prompt, label="Task decomposition", timeout=300)
        if not raw:
            if self._llm.dry_run:
                return
            logger.warn("Task decomposition failed, skipping execution phase")
            return

        task_list = extract_json(raw)
        tasks = task_list.get("tasks", [])
        if not tasks:
            logger.warn("No tasks decomposed, skipping execution phase")
            return

        logger.info(f"Decomposed {len(tasks)} tasks for execution")
        agent_map = {a.name: a for a in ctx.agents}
        transcript = session.transcript
        max_task_retries = 3

        for idx, task_def in enumerate(tasks):
            task_agent_name = task_def.get("agent", "")
            task_desc = task_def.get("task", "")
            agent = agent_map.get(task_agent_name, ctx.agents[0])

            print(f"\n{BOLD}--- Executing task {idx + 1}/{len(tasks)}: "
                  f"{agent.name} ---{NC}")
            logger.info(f"Task: {task_desc[:100]}")

            response = agent_svc.execute(agent, ctx, task_def)
            if not response:
                response = "[agent declined]"

            # Write execution to transcript
            with transcript.open("a", encoding="utf-8") as f:
                t = datetime.now().strftime("%H:%M")
                f.write(f"### Execution {idx + 1} -- {agent.name} [{t}]\n"
                        f"**Task**: {task_desc}\n\n"
                        f"{response}\n\n---\n\n")

            # Verify with retry loop
            for retry in range(max_task_retries):
                verification = self.verify_task(ctx, task_def, response)
                v_status = verification.get("status", "pass")
                v_details = verification.get("details", "")

                verify_notes = session.notes_dir / "_verification"
                verify_notes.mkdir(parents=True, exist_ok=True)
                suffix = f"-retry{retry}" if retry > 0 else ""
                (verify_notes / f"exec-{idx + 1}{suffix}.md").write_text(
                    f"# Verification -- Execution {idx + 1}\n\n"
                    f"**Status**: {v_status}\n"
                    f"**Details**: {v_details}\n",
                    encoding="utf-8",
                )

                if v_status == "pass":
                    logger.ok(f"Task {idx + 1} verified: {v_details[:80]}")
                    break

                if retry < max_task_retries - 1:
                    logger.warn(f"Task {idx + 1} failed (attempt {retry + 1}/"
                         f"{max_task_retries}): {v_details[:80]}")
                    retry_task = dict(task_def)
                    retry_task["task"] = (task_desc
                                          + f"\n\nPREVIOUS ATTEMPT FAILED: "
                                          + v_details)
                    response = agent_svc.execute(agent, ctx, retry_task)
                else:
                    logger.warn(f"Task {idx + 1} failed after {max_task_retries} "
                         f"attempts: {v_details[:80]}")

        logger.ok("Execution phase complete")
