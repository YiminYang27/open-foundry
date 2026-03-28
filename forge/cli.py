#!/usr/bin/env python3
"""
forge.cli -- Multi-agent discussion orchestrator

Runs a structured discussion between LLM agents with distinct
perspectives, moderated by an orchestrator that picks speakers
and detects consensus. All discussion is recorded to a readable
transcript.

Usage:
  ./scripts/forge.py <mission> [OPTIONS]

Arguments:
  <mission>   Path to a mission directory or MISSION.md file

Options:
  --max-turns N       Override max utterances (default: from mission file or 20)
  --model MODEL       Override model for all claude -p calls
  --resume DIR        Resume from a previous run directory
  --synthesize-only   Skip discussion, run finalize + synthesize (requires --resume)
  --dry-run           Print prompts without calling Claude
  --help              Show this help message

Intervention controls (during a running discussion):
  Ctrl+\\              Pause after current turn completes
  touch PAUSE         Pause from another terminal window

Examples:
  ./scripts/forge.py gold-price-outlook
  ./scripts/forge.py gold-price-outlook --max-turns 50 --model opus
  ./scripts/forge.py gold-price-outlook --resume gold-price-outlook-20260322-001929
  ./scripts/forge.py gold-price-outlook --resume gold-price-outlook-20260322-001929 --synthesize-only
  ./scripts/forge.py gold-price-outlook --model opus
"""

import argparse
from collections import Counter
import json
import re
import shutil
import signal
import sys
import termios
from datetime import datetime
from pathlib import Path

from forge.log import (info, ok, warn, fatal, speaker_line,
                       set_session_log, CYAN, BOLD, NC)
from forge.models import Agent, Orchestrator, Session
from forge.prompts import load_template
from forge.llm import ClaudeCLI, extract_json
from forge.roles import RoleStore, parse_mission
from forge.session_io import (get_transcript_context,
                              truncate_transcript_for_closing,
                              load_state, inject_operator_turn)

_pause_requested = False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def orchestrator_pick(session: Session, agents: list[Agent], orch: Orchestrator,
                      agent_list_str: str, max_turns: int, llm: ClaudeCLI,
                      recent_turns: int = 10) -> dict:

    transcript_ctx = get_transcript_context(session.transcript, session.utterances,
                                            recent_turns=recent_turns)

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
        # Show last 5 decisions for context
        recent = lines[-5:] if len(lines) > 5 else lines
        decision_parts = []
        # Compute starting turn number: current utterances - len(recent)
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

    # When the orchestrator supports verification, it can also assign
    # execute actions (implementation tasks) in addition to speak actions.
    action_block = ""
    if orch.verify_persona:
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
                           agent_list_str=agent_list_str,
                           pick_persona=orch.pick_persona,
                           turn_number=session.utterances + 1,
                           max_turns=max_turns,
                           speaker_stats=speaker_stats,
                           recent_decisions=recent_decisions,
                           agent_statuses=agent_statuses,
                           transcript_ctx=transcript_ctx,
                           action_block=action_block)

    raw = llm.complete(prompt, label="Orchestrator", timeout=120)
    if not raw:
        if llm.dry_run:
            return {"speaker": agents[0].name, "reasoning": "dry run"}
        warn("Orchestrator returned empty response")
        return {"speaker": "FALLBACK", "reasoning": "orchestrator failed"}

    # Parse JSON -- handle markdown fences or extra text
    parsed = extract_json(raw)

    # Log decision
    with session.orch_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(parsed) + "\n")

    return parsed


# ---------------------------------------------------------------------------
# Agent speak
# ---------------------------------------------------------------------------


def _parse_status_signal(response: str) -> dict:
    """Extract status marker from last lines of agent response."""
    for line in reversed(response.strip().splitlines()):
        line = line.strip()
        if line == "[ANALYSIS_COMPLETE]":
            return {"signal": "ANALYSIS_COMPLETE"}
        if line.startswith("[NEEDS_DATA:") and line.endswith("]"):
            return {"signal": "NEEDS_DATA",
                    "item": line[len("[NEEDS_DATA:"):-1]}
        if line.startswith("[DISAGREE_WITH:") and line.endswith("]"):
            parts = line[len("[DISAGREE_WITH:"):-1].split(":", 1)
            return {"signal": "DISAGREE_WITH", "agent": parts[0],
                    "topic": parts[1] if len(parts) > 1 else ""}
        if line == "[INCONCLUSIVE]":
            return {"signal": "INCONCLUSIVE"}
    return {"signal": "NONE"}


def agent_speak(session: Session, agent: Agent, topic_body: str,
                max_turns: int, llm: ClaudeCLI,
                mission_dir: Path | None = None,
                recent_turns: int = 10) -> str:

    transcript_ctx = get_transcript_context(session.transcript, session.utterances,
                                            recent_turns=recent_turns)

    refs_block = ""
    if mission_dir:
        refs_dir = mission_dir / "references"
        if refs_dir.is_dir() and any(refs_dir.iterdir()):
            refs_block = (
                f"\nREFERENCE MATERIALS: {refs_dir}/\n"
                f"Read files in this directory for background data provided\n"
                f"by the mission author. Cite them when relevant.\n"
            )

    prompt = load_template("agent_speak",
                           agent_name=agent.name,
                           agent_persona=agent.persona,
                           topic_body=topic_body,
                           refs_block=refs_block,
                           transcript_ctx=transcript_ctx,
                           notes_dir=session.notes_dir,
                           turn_number=session.utterances + 1,
                           max_turns=max_turns)

    result = llm.complete(prompt, label=f"Agent {agent.name}")
    if not result:
        return f"[dry run response from {agent.name}]" if llm.dry_run else "[agent declined]"
    return result


# ---------------------------------------------------------------------------
# Agent execute (implementation action)
# ---------------------------------------------------------------------------

def agent_execute(session: Session, agent: Agent, topic_body: str,
                  task: dict, max_turns: int, llm: ClaudeCLI,
                  mission_dir: Path | None = None,
                  recent_turns: int = 10) -> str:
    """Have an agent execute a specific implementation task."""

    transcript_ctx = get_transcript_context(session.transcript, session.utterances,
                                            recent_turns=recent_turns)

    refs_block = ""
    if mission_dir:
        refs_dir = mission_dir / "references"
        if refs_dir.is_dir() and any(refs_dir.iterdir()):
            refs_block = (
                f"\nREFERENCE MATERIALS: {refs_dir}/\n"
                f"Read files in this directory for specs, plans, and context.\n"
            )

    task_desc = task.get("task", "")
    verify_criteria = task.get("verify", "")

    verify_block = ""
    if verify_criteria:
        verify_block = f"\nVERIFICATION CRITERIA:\n{verify_criteria}\n"

    # Build handoff context from orchestrator reasoning
    handoff_parts = []
    reasoning = task.get("reasoning", "")
    if reasoning:
        handoff_parts.append(f"Decision: {reasoning}")
    # Include recent speakers as contributing agents
    recent_speakers = session.speakers_history[-5:] if session.speakers_history else []
    if recent_speakers:
        handoff_parts.append(f"Contributing agents: {', '.join(dict.fromkeys(recent_speakers))}")
    handoff_context = "\n".join(handoff_parts) if handoff_parts else "(none)"

    prompt = load_template("agent_execute",
                           agent_name=agent.name,
                           agent_persona=agent.persona,
                           topic_body=topic_body,
                           refs_block=refs_block,
                           task_desc=task_desc,
                           verify_block=verify_block,
                           handoff_context=handoff_context,
                           notes_dir=session.notes_dir,
                           transcript_ctx=transcript_ctx,
                           turn_number=session.utterances + 1,
                           max_turns=max_turns)

    result = llm.complete(prompt, label=f"Agent {agent.name} (execute)",
                          timeout=600)
    if not result:
        return (f"[dry run execution from {agent.name}]"
                if llm.dry_run else "[agent declined]")
    return result


# ---------------------------------------------------------------------------
# Verify task (after execute action)
# ---------------------------------------------------------------------------

def verify_task(session: Session, orch: Orchestrator, task: dict,
                agent_response: str, llm: ClaudeCLI) -> dict:
    """Verify a completed task using the orchestrator's verification persona."""

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

    raw = llm.complete(prompt, label="Verification", timeout=300)
    if not raw:
        return {"status": "pass",
                "details": "dry run" if llm.dry_run else "verification call failed, assuming pass"}

    return extract_json(raw)


# ---------------------------------------------------------------------------
# Finalize and synthesize
# ---------------------------------------------------------------------------

def finalize(session: Session, orch: Orchestrator, llm: ClaudeCLI,
             consensus_status: str) -> None:

    transcript_content = session.transcript.read_text(encoding="utf-8")

    # Speaker breakdown (assumes snake_case agent names -- no spaces)
    counts: dict[str, int] = Counter()
    for line in transcript_content.splitlines():
        if line.startswith("### Turn "):
            parts = line.split(" -- ")
            if len(parts) >= 2:
                counts[parts[1].split()[0].strip()] += 1

    breakdown = "\n".join(f"- {name}: {count} turns"
                          for name, count in sorted(counts.items()))

    # Use truncated transcript for the prompt to avoid exceeding context window.
    # Full transcript is still used above for speaker counting (cheap string scan).
    truncated = truncate_transcript_for_closing(session.transcript)

    summary_prompt = load_template("finalize",
                                    close_persona=orch.close_persona,
                                    truncated=truncated)

    summary = llm.complete(summary_prompt, label="Closing summary")
    if not summary:
        summary = ("[dry run closing summary]" if llm.dry_run
                   else "[failed to generate closing summary]")

    # Write closing summary to independent file (overwrite on resume)
    closing_file = session.work_dir / "closing.md"
    closing_file.write_text(
        f"# Closing Summary\n\n"
        f"{summary}\n\n"
        f"## Statistics\n\n"
        f"- Total turns: {session.utterances}\n"
        f"- Speaker breakdown:\n{breakdown}\n"
        f"- Consensus: {consensus_status}\n"
        f"- Model: {llm.model}\n"
        f"- Completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )

    ok(f"Closing summary written to {closing_file}")


def synthesize(session: Session, role_store: RoleStore, topic_body: str,
               llm: ClaudeCLI) -> None:
    print(f"\n{BOLD}--- Synthesizing reference document ---{NC}")

    synth_persona = role_store.get_synthesizer_persona()
    if synth_persona is None:
        warn("Synthesizer role not found -- skipping synthesis")
        return

    synthesis_file = session.work_dir / "synthesis.md"

    # Build notes inventory
    notes_inventory_lines = []
    for p in sorted(session.notes_dir.rglob("*.md")):
        if p.name != "files-read.md":
            rel = p.relative_to(session.notes_dir)
            notes_inventory_lines.append(f"{rel} ({p.stat().st_size} bytes)")
    notes_inventory = "\n".join(notes_inventory_lines)

    # Check for archived previous synthesis (from --feedback runs)
    prev_synthesis_block = ""
    archived = sorted(session.work_dir.glob("synthesis-*.md"))
    if archived:
        latest_archived = archived[-1]
        prev_synthesis_block = (
            f"\nPREVIOUS SYNTHESIS: {latest_archived}\n"
            f"Read this to understand the prior conclusions. The human provided\n"
            f"feedback that triggered additional discussion -- focus on what changed.\n"
        )

    synth_prompt = load_template("synthesize",
                                  synth_persona=synth_persona,
                                  topic_body=topic_body,
                                  notes_dir=session.notes_dir,
                                  notes_inventory=notes_inventory,
                                  transcript_path=session.transcript,
                                  closing_path=session.work_dir / "closing.md",
                                  prev_synthesis_block=prev_synthesis_block,
                                  synthesis_file=synthesis_file)

    if llm.dry_run:
        # dry_run: provider already logged via complete(), write placeholder
        llm.complete(synth_prompt, label="Synthesizer")
        synthesis_file.write_text("[dry run synthesis]\n", encoding="utf-8")
        return

    info("Running synthesizer (this may take a few minutes)...")
    # Synthesizer writes synthesis.md directly via file tools.
    # Use stream() for capture_output=False (live progress).
    if hasattr(llm, 'stream'):
        synth_timeout = 1800
        synth_retries = 3
        info(f"Synthesizer timeout: {synth_timeout}s x {synth_retries} retries")
        for attempt in range(synth_retries):
            # Clear partial synthesis from previous failed attempt
            if attempt > 0 and synthesis_file.exists():
                backup = synthesis_file.with_suffix(f".attempt{attempt}.md")
                synthesis_file.rename(backup)
                info(f"Moved partial synthesis to {backup.name}")
            rc = llm.stream(synth_prompt, label="Synthesizer",
                            timeout=synth_timeout, max_retries=1)
            if rc == 0:
                break
            if attempt < synth_retries - 1:
                info(f"Retrying synthesizer "
                     f"(attempt {attempt + 2}/{synth_retries})...")
    else:
        # Fallback for providers without stream()
        result = llm.complete(synth_prompt, label="Synthesizer",
                              timeout=1800)
        if result:
            synthesis_file.write_text(result, encoding="utf-8")

    if synthesis_file.exists():
        lines = len(synthesis_file.read_text(encoding="utf-8").splitlines())
        ok(f"Synthesis written to {synthesis_file} ({lines} lines)")
    else:
        warn(f"Synthesizer did not produce {synthesis_file}")


# ---------------------------------------------------------------------------
# Post-discussion execution phase
# ---------------------------------------------------------------------------

def execution_phase(session: Session, agents: list[Agent],
                    orch: Orchestrator, agent_list_str: str,
                    topic_body: str, llm: ClaudeCLI,
                    mission_dir: Path | None = None) -> None:
    """Decompose closing summary into tasks and execute them."""
    closing_file = session.work_dir / "closing.md"
    if not closing_file.exists():
        warn("No closing.md found, skipping execution phase")
        return

    if not orch.verify_persona:
        warn("Orchestrator has no verification persona, skipping execution phase")
        return

    print(f"\n{BOLD}--- Post-Discussion Execution Phase ---{NC}")

    closing_summary = closing_file.read_text(encoding="utf-8")
    prompt = load_template("task_decompose",
                           verify_persona=orch.verify_persona,
                           closing_summary=closing_summary,
                           agent_list_str=agent_list_str)

    raw = llm.complete(prompt, label="Task decomposition", timeout=300)
    if not raw:
        if llm.dry_run:
            return
        warn("Task decomposition failed, skipping execution phase")
        return

    task_list = extract_json(raw)
    tasks = task_list.get("tasks", [])
    if not tasks:
        warn("No tasks decomposed, skipping execution phase")
        return

    info(f"Decomposed {len(tasks)} tasks for execution")
    agent_map = {a.name: a for a in agents}
    transcript = session.transcript
    max_task_retries = 3

    for idx, task_def in enumerate(tasks):
        task_agent_name = task_def.get("agent", "")
        task_desc = task_def.get("task", "")
        agent = agent_map.get(task_agent_name, agents[0])

        # Check dependencies
        depends = task_def.get("depends_on", [])
        # (Dependencies are tracked by index -- simple sequential ordering
        # handles this since we execute in order.)

        print(f"\n{BOLD}--- Executing task {idx + 1}/{len(tasks)}: "
              f"{agent.name} ---{NC}")
        info(f"Task: {task_desc[:100]}")

        response = agent_execute(session, agent, topic_body, task_def,
                                 9999, llm,
                                 mission_dir=mission_dir)
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
            verification = verify_task(session, orch, task_def, response, llm)
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
                ok(f"Task {idx + 1} verified: {v_details[:80]}")
                break

            if retry < max_task_retries - 1:
                warn(f"Task {idx + 1} failed (attempt {retry + 1}/"
                     f"{max_task_retries}): {v_details[:80]}")
                retry_task = dict(task_def)
                retry_task["task"] = (task_desc
                                      + f"\n\nPREVIOUS ATTEMPT FAILED: "
                                      + v_details)
                response = agent_execute(session, agent, topic_body,
                                         retry_task, 9999, llm,
                                         mission_dir=mission_dir)
            else:
                warn(f"Task {idx + 1} failed after {max_task_retries} "
                     f"attempts: {v_details[:80]}")

    ok("Execution phase complete")


# ---------------------------------------------------------------------------
# Synthesis review
# ---------------------------------------------------------------------------

def review_synthesis(session: Session, llm: ClaudeCLI) -> dict:
    """Review synthesis for accuracy against transcript and closing."""
    synthesis_file = session.work_dir / "synthesis.md"
    closing_file = session.work_dir / "closing.md"

    if not synthesis_file.exists() or not closing_file.exists():
        return {"status": "APPROVED", "notes": "missing files, skipping review"}

    print(f"\n{BOLD}--- Reviewing synthesis ---{NC}")

    prompt = load_template("synthesis_review",
                           transcript_path=session.transcript,
                           closing_path=closing_file,
                           synthesis_path=synthesis_file)

    raw = llm.complete(prompt, label="Synthesis review", timeout=600)
    if not raw:
        return {"status": "APPROVED",
                "notes": "dry run" if llm.dry_run else "review call failed, assuming pass"}

    result = extract_json(raw)

    # Save review result
    review_file = session.work_dir / "review.json"
    review_file.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                           encoding="utf-8")

    status = result.get("status", "APPROVED")
    if status == "APPROVED":
        ok(f"Synthesis approved: {result.get('notes', '')[:100]}")
    else:
        issues = result.get("issues", [])
        warn(f"Synthesis review found {len(issues)} issue(s)")
        for issue in issues[:5]:
            warn(f"  [{issue.get('type', '?')}] {issue.get('description', '')[:80]}")

    return result


# ---------------------------------------------------------------------------
# Fallback speaker selection (round-robin)
# ---------------------------------------------------------------------------

def next_round_robin(agents: list[Agent], last_speaker: str) -> str:
    if not last_speaker:
        return agents[0].name
    for i, a in enumerate(agents):
        if a.name == last_speaker:
            return agents[(i + 1) % len(agents)].name
    return agents[0].name


# ---------------------------------------------------------------------------
# Intervention (human-in-the-loop)
# ---------------------------------------------------------------------------

def _on_pause_signal(*_):
    global _pause_requested
    _pause_requested = True
    print()
    info("Pause requested -- waiting for current turn to finish...")


def _check_pause(session: Session) -> bool:
    """Return True if a pause has been requested via signal or PAUSE file."""
    global _pause_requested
    if _pause_requested:
        _pause_requested = False
        return True
    pause_file = session.work_dir / "PAUSE"
    if pause_file.exists():
        pause_file.unlink()
        info("PAUSE file detected")
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-agent discussion orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        add_help=True,
    )
    parser.add_argument("topic_file", help="Mission slug or path (e.g. gold-price-outlook)")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="Override max utterances")
    parser.add_argument("--model", default=None,
                        help="Override model (opus/sonnet/haiku)")
    parser.add_argument("--resume", default=None, metavar="SESSION",
                        help="Resume session (slug-timestamp, e.g. gold-price-outlook-20260322-001929)")
    parser.add_argument("--synthesize-only", action="store_true",
                        help="Skip discussion, run finalize + synthesize (requires --resume)")
    parser.add_argument("--feedback", default=None, metavar="TEXT",
                        help="Inject human feedback into a completed session and resume discussion")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling Claude")
    args = parser.parse_args()

    if args.feedback and not args.resume:
        fatal("--feedback requires --resume to specify which session to continue")

    if args.synthesize_only and not args.resume:
        fatal("--synthesize-only requires --resume to specify the session")

    # Resolve paths -- find project root by walking up to the directory
    # containing CLAUDE.md (works whether invoked from forge/ or scripts/).
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    if not (project_root / "CLAUDE.md").exists():
        # Likely running from forge/ -- go one more level up
        project_root = project_root.parent
    role_store = RoleStore(project_root / "roles")

    topic_path = Path(args.topic_file)
    if not topic_path.is_absolute():
        # Try as slug under missions/ first, then as literal path
        missions_dir = project_root / "missions"
        candidate = missions_dir / topic_path
        if candidate.exists():
            topic_path = candidate
        else:
            topic_path = project_root / topic_path
    # Support both directory (find MISSION.md inside) and direct file path
    if topic_path.is_dir():
        mission_file = topic_path / "MISSION.md"
        if not mission_file.exists():
            fatal(f"MISSION.md not found in {topic_path}")
        topic_path = mission_file
    if not topic_path.exists():
        fatal(f"Mission not found: {topic_path}")

    resume_dir = None
    if args.resume:
        resume_dir = Path(args.resume)
        if not resume_dir.is_absolute():
            # Try as session name under sessions/ first, then as literal path
            sessions_dir = project_root / "sessions"
            candidate = sessions_dir / resume_dir
            if candidate.exists():
                resume_dir = candidate
            else:
                resume_dir = project_root / resume_dir
        if not resume_dir.exists():
            fatal(f"Resume directory not found: {resume_dir}")

    # Check prerequisites
    if not shutil.which("claude"):
        fatal("claude CLI not found in PATH")

    # Parse mission
    try:
        (agent_names, max_turns, model, orch_name, title, topic_body,
         execute_after) = parse_mission(topic_path)
    except ValueError as e:
        fatal(str(e))

    # Apply overrides
    if args.max_turns is not None:
        max_turns = args.max_turns
    if args.model is not None:
        model = args.model

    if not agent_names:
        fatal("No agents defined in topic file")

    # Construct LLM provider
    llm = ClaudeCLI(model=model, dry_run=args.dry_run)

    # Load roles
    info("Validating role files...")
    agents: list[Agent] = []
    for name in agent_names:
        agents.append(role_store.get_agent(name))
    ok(f"All {len(agents)} role files validated")

    # Load orchestrator
    orch = role_store.get_orchestrator(orch_name)
    info(f"Orchestrator: {orch_name}")

    # Build agent list string for orchestrator prompts
    agent_list_str = "".join(f"- {a.name}: {a.expertise}\n" for a in agents)

    # Set up session directory
    if resume_dir:
        work_dir = resume_dir
        info(f"Resuming from {work_dir}")
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = topic_path.parent.name if topic_path.name == "MISSION.md" else topic_path.stem
        sessions_dir = project_root / "sessions"
        work_dir = sessions_dir / f"{slug}-{timestamp}"
        work_dir.mkdir(parents=True, exist_ok=True)
        # Store a pointer to the mission source instead of copying.
        # Missions may contain a references/ directory with large files;
        # duplicating them into every session would waste space.
        (work_dir / "MISSION.md").write_text(
            f"<!-- source: {topic_path} -->\n"
            + topic_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    transcript = work_dir / "transcript.md"
    state_file = work_dir / "state.json"
    orch_log = work_dir / "orchestrator.log"
    utterances_dir = work_dir / "utterances"
    notes_dir = work_dir / "notes"

    # Enable session-level runtime log (captures all info/warn/ok/err/speaker output)
    set_session_log(work_dir / "runtime.log")

    utterances_dir.mkdir(exist_ok=True)
    for a in agents:
        (notes_dir / a.name).mkdir(parents=True, exist_ok=True)
    (notes_dir / "_operator").mkdir(parents=True, exist_ok=True)

    # Clean up leftover PAUSE file from previous session
    pause_sentinel = work_dir / "PAUSE"
    if pause_sentinel.exists():
        pause_sentinel.unlink()
        warn("Removed leftover PAUSE file from previous session")

    session = Session(
        work_dir=work_dir,
        transcript=transcript,
        state_file=state_file,
        orch_log=orch_log,
        utterances_dir=utterances_dir,
        notes_dir=notes_dir,
    )

    def _update_state(status: str) -> None:
        state = {
            "utterances": session.utterances,
            "max_turns": max_turns,
            "status": status,
            "last_speaker": session.last_speaker,
            "consecutive_count": session.consecutive_count,
            "speakers_history": session.speakers_history,
            "agents": [a.name for a in agents],
            "model": model,
            "mission_source": str(topic_path),
            "interventions": session.interventions,
        }
        session.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Initialize or resume
    if resume_dir and state_file.exists():
        state = load_state(state_file)
        session.utterances = state.get("utterances", 0)
        session.last_speaker = state.get("last_speaker", "")
        session.consecutive_count = state.get("consecutive_count", 0)
        session.speakers_history = state.get("speakers_history", [])
        # Backward compat: rebuild from transcript for old state files.
        # Triggers when speakers_history is empty ([] is falsy) or missing
        # from state.json (state.get returns []).
        if not session.speakers_history and session.utterances > 0 and session.transcript.exists():
            for line in session.transcript.read_text(encoding="utf-8").splitlines():
                if line.startswith("### Turn "):
                    parts = line.split(" -- ")
                    if len(parts) >= 2:
                        session.speakers_history.append(parts[1].split()[0].strip())
        # Warn if session already completed
        if state.get("status") == "completed":
            if args.feedback:
                # --feedback on a completed session: archive old outputs and inject
                archive_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                for fname in ("closing.md", "synthesis.md"):
                    fpath = work_dir / fname
                    if fpath.exists():
                        stem = fpath.stem
                        archived = fpath.with_name(f"{stem}-{archive_ts}.md")
                        fpath.rename(archived)
                        info(f"Archived {fname} -> {archived.name}")
                info("Injecting feedback and resuming discussion")
            else:
                synthesis_exists = (work_dir / "synthesis.md").exists()
                if not synthesis_exists:
                    warn("Session already completed but synthesis.md is missing.")
                    warn(f"Consider: ./scripts/forge.py {args.topic_file} "
                         f"--resume {args.resume} --synthesize-only")
                else:
                    warn("Session already completed (synthesis.md exists).")
                    warn("Re-entering discussion loop will add turns beyond "
                         "original completion. Use --synthesize-only to re-run "
                         "synthesis only.")
        session.interventions = state.get("interventions", [])
        info(f"Resuming at turn {session.utterances + 1}, last speaker: {session.last_speaker}")
    else:
        session.utterances = 0
        session.last_speaker = ""
        session.consecutive_count = 0

        agents_str = ", ".join(a.name for a in agents)
        transcript.write_text(
            f"# Discussion: {title}\n\n"
            f"> Started: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"> Agents: {agents_str}\n"
            f"> Max turns: {max_turns}\n"
            f"> Model: {model}\n\n"
            f"## Topic\n{topic_body}\n\n"
            f"## Discussion\n\n",
            encoding="utf-8",
        )
        _update_state("starting")
        orch_log.touch()

    # Graceful shutdown
    def on_interrupt(*_):  # signal handler: receives (signum, frame) but doesn't use them
        print()
        warn(f"Interrupted at turn {session.utterances}")
        _update_state("interrupted")
        info(f"Resume with: ./scripts/forge.py {args.topic_file} --resume {work_dir}")
        sys.exit(130)

    signal.signal(signal.SIGINT, on_interrupt)
    signal.signal(signal.SIGTERM, on_interrupt)
    if hasattr(signal, 'SIGQUIT'):
        signal.signal(signal.SIGQUIT, _on_pause_signal)
    if hasattr(signal, 'SIGUSR1'):
        signal.signal(signal.SIGUSR1, _on_pause_signal)

    # Banner
    print(f"\n{BOLD}=== Forum Discussion ==={NC}\n")
    info(f"Topic:     {title}")
    info(f"Agents:    {' '.join(a.name for a in agents)}")
    info(f"Max turns: {max_turns}")
    info(f"Model:     {model}")
    info(f"Output:    {work_dir}")
    if resume_dir:
        info(f"Resuming from turn {session.utterances + 1}")
    if sys.stdout.isatty() and not args.dry_run:
        info(f"Pause:     Ctrl+\\\\ or touch {work_dir}/PAUSE")
    print()

    # Inject feedback before entering main loop
    if args.feedback and resume_dir:
        inject_operator_turn(session, args.feedback)
        _update_state("running")

    # Synthesize-only mode: skip discussion, run finalize + synthesize
    if args.synthesize_only:
        if not state_file.exists():
            fatal(f"No state.json found in {work_dir} -- cannot run synthesize-only")
        info(f"Synthesize-only mode: skipping discussion loop")
        info(f"Session has {session.utterances} turns")

        closing_file = work_dir / "closing.md"
        if closing_file.exists():
            info("closing.md exists, re-running synthesis only")
        else:
            info("closing.md missing, running finalize + synthesis")
            finalize(session, orch, llm, "unknown (synthesize-only mode)")

        synthesize(session, role_store, topic_body, llm)
        if not llm.dry_run:
            review_synthesis(session, llm)

        synthesis = work_dir / "synthesis.md"
        if synthesis.exists():
            _update_state("completed")
            ok(f"Synthesis written to {synthesis}")
        else:
            warn("Synthesis was not produced")
        return

    # Main loop
    agent_names_set = {a.name for a in agents}
    recent_window = max(len(agents) + 2, 10)

    while session.utterances < max_turns:
        print(f"{BOLD}--- Orchestrator picking speaker (turn {session.utterances + 1}/{max_turns}) ---{NC}")

        pick_result = orchestrator_pick(
            session, agents, orch, agent_list_str, max_turns, llm,
            recent_turns=recent_window
        )

        speaker = pick_result.get("speaker", "FALLBACK")
        reasoning = pick_result.get("reasoning", "")
        action = pick_result.get("action", "speak")

        # Save orchestrator utterance
        orch_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        (utterances_dir / f"{orch_ts}-host.md").write_text(
            f"# Orchestrator -- Turn {session.utterances + 1}\n\n"
            f"**Speaker picked**: {speaker}\n"
            f"**Action**: {action}\n"
            f"**Reasoning**: {reasoning}\n"
            + (f"**Task**: {pick_result.get('task', '')}\n" if action == "execute" else ""),
            encoding="utf-8",
        )

        # Consensus?
        if speaker == "CONSENSUS":
            ok(f"Consensus reached: {reasoning}")
            _update_state("completed")
            finalize(session, orch, llm, "yes")
            if execute_after:
                execution_phase(session, agents, orch, agent_list_str,
                                topic_body, llm,
                                mission_dir=topic_path.parent)
            synthesize(session, role_store, topic_body, llm)
            if not llm.dry_run:
                review_synthesis(session, llm)
            print(f"\n{BOLD}=== Forum Complete (consensus at turn {session.utterances}) ==={NC}")
            info(f"Transcript: {transcript}")
            synthesis = work_dir / "synthesis.md"
            if synthesis.exists():
                info(f"Synthesis: {synthesis}")
            return

        # Fallback to round-robin if orchestrator failed or picked unknown agent
        if speaker == "FALLBACK" or speaker not in agent_names_set:
            if speaker != "FALLBACK":
                warn(f"Orchestrator picked unknown agent '{speaker}', falling back to round-robin")
            else:
                warn("Orchestrator fallback -> round-robin")
            speaker = next_round_robin(agents, session.last_speaker)
            action = "speak"  # fallback always speaks

        # Anti-loop guard: same agent 3x consecutive -> force rotation
        if speaker == session.last_speaker:
            session.consecutive_count += 1
        else:
            session.consecutive_count = 1

        if session.consecutive_count >= 3:
            warn(f"Agent {speaker} picked 3x in a row, forcing rotation")
            speaker = next_round_robin(agents, speaker)
            session.consecutive_count = 1

        action_label = f" (execute)" if action == "execute" else ""
        speaker_line(speaker, f"{reasoning}{action_label}")

        # Find agent object
        agent = next((a for a in agents if a.name == speaker), agents[0])

        # Agent speaks or executes based on orchestrator's action decision
        if action == "execute":
            response = agent_execute(session, agent, topic_body, pick_result,
                                     max_turns, llm,
                                     mission_dir=topic_path.parent,
                                     recent_turns=recent_window)
        else:
            response = agent_speak(session, agent, topic_body, max_turns, llm,
                                   mission_dir=topic_path.parent,
                                   recent_turns=recent_window)
        if not response:
            response = "[agent declined]"

        # Save agent utterance
        agent_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = speaker.replace("/", "_")
        (utterances_dir / f"{agent_ts}-{safe_name}.md").write_text(
            f"# {speaker} -- Turn {session.utterances + 1}"
            + (f" (execute)\n\n**Task**: {pick_result.get('task', '')}\n\n" if action == "execute" else "\n\n")
            + f"{response}\n",
            encoding="utf-8",
        )

        # Append to transcript
        turn_time = datetime.now().strftime("%H:%M")
        with transcript.open("a", encoding="utf-8") as f:
            f.write(f"### Turn {session.utterances + 1} -- {speaker} [{turn_time}]"
                    + (f" [execute]" if action == "execute" else "") + "\n"
                    + (f"**Task**: {pick_result.get('task', '')}\n\n" if action == "execute" else "")
                    + f"{response}\n\n---\n\n")

        session.utterances += 1
        session.last_speaker = speaker
        session.speakers_history.append(speaker)

        # Parse agent status signal (from speak actions)
        if action == "speak" and response:
            session.agent_statuses[speaker] = _parse_status_signal(response)

        # Verify after execute actions (with retry loop)
        if action == "execute" and orch.verify_persona and not llm.dry_run:
            max_task_retries = 3
            for retry_attempt in range(max_task_retries):
                attempt_label = (f" (retry {retry_attempt}/{max_task_retries})"
                                 if retry_attempt > 0 else "")
                print(f"{BOLD}--- Verifying task{attempt_label} ---{NC}")
                verification = verify_task(session, orch, pick_result, response, llm)
                v_status = verification.get("status", "pass")
                v_details = verification.get("details", "")

                # Save verification to notes
                verify_notes = session.notes_dir / "_verification"
                verify_notes.mkdir(parents=True, exist_ok=True)
                suffix = f"-retry{retry_attempt}" if retry_attempt > 0 else ""
                (verify_notes / f"turn-{session.utterances}{suffix}.md").write_text(
                    f"# Verification -- Turn {session.utterances}{attempt_label}\n\n"
                    f"**Status**: {v_status}\n"
                    f"**Details**: {v_details}\n",
                    encoding="utf-8",
                )

                # Append verification to transcript
                with transcript.open("a", encoding="utf-8") as f:
                    v_time = datetime.now().strftime("%H:%M")
                    f.write(f"### Verification -- Turn {session.utterances}"
                            f"{attempt_label} [{v_time}]\n"
                            f"**Status**: {v_status}\n"
                            f"**Details**: {v_details}\n\n---\n\n")

                if v_status == "pass":
                    ok(f"Task verified: {v_details[:100]}")
                    break

                # Retry: re-execute with failure feedback
                if retry_attempt < max_task_retries - 1:
                    warn(f"Task failed verification (attempt "
                         f"{retry_attempt + 1}/{max_task_retries}): "
                         f"{v_details[:100]}")
                    retry_task = dict(pick_result)
                    retry_task["task"] = (pick_result.get("task", "")
                                          + f"\n\nPREVIOUS ATTEMPT FAILED: "
                                          + v_details)
                    response = agent_execute(
                        session, agent, topic_body, retry_task,
                        max_turns, llm,
                        mission_dir=topic_path.parent,
                        recent_turns=recent_window)
                    # Append retry response to transcript
                    with transcript.open("a", encoding="utf-8") as f:
                        r_time = datetime.now().strftime("%H:%M")
                        f.write(f"### Turn {session.utterances} -- {speaker}"
                                f" [execute retry {retry_attempt + 1}]"
                                f" [{r_time}]\n"
                                f"**Task**: {retry_task.get('task', '')}\n\n"
                                f"{response}\n\n---\n\n")
                else:
                    warn(f"Task failed after {max_task_retries} attempts: "
                         f"{v_details[:100]}")

        _update_state("running")

        ok(f"Turn {session.utterances}/{max_turns} complete ({speaker}{action_label})")

        # Check for pause triggers (Ctrl+\ signal or PAUSE file)
        if not llm.dry_run and _check_pause(session) and sys.stdout.isatty():
            _update_state("paused")
            # Flush any keystrokes typed while the agent was running,
            # so input() waits for fresh, intentional input.
            try:
                termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
            except (termios.error, OSError):
                pass
            try:
                print(f"\n{BOLD}--- Paused after turn {session.utterances}/{max_turns} ---{NC}")
                msg = input("Type message to inject (Enter to resume): ").strip()
            except (EOFError, KeyboardInterrupt):
                msg = ""
            if msg:
                inject_operator_turn(session, msg)
            _update_state("running")

        print()

    # Max turns reached
    warn(f"Max turns ({max_turns}) reached without consensus")
    _update_state("completed")
    finalize(session, orch, llm, "no (max turns reached)")
    if execute_after:
        execution_phase(session, agents, orch, agent_list_str,
                        topic_body, llm,
                        mission_dir=topic_path.parent)
    synthesize(session, role_store, topic_body, llm)
    if not llm.dry_run:
        review_synthesis(session, llm)

    print(f"\n{BOLD}=== Forum Complete ({session.utterances} turns, no consensus) ==={NC}")
    info(f"Transcript: {transcript}")
    synthesis = work_dir / "synthesis.md"
    if synthesis.exists():
        info(f"Synthesis: {synthesis}")


if __name__ == "__main__":
    main()
