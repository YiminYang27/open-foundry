"""Session I/O management for the open-foundry orchestrator.

Handles session directory creation/resume, transcript operations,
state persistence, utterance filing, and operator intervention.
"""

import json
import re
from datetime import datetime
from pathlib import Path

from forge.utils.logger import info, warn, ok
from forge.models import Agent, Session


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def create_session(project_root: Path, slug: str, topic_path: Path,
                   agents: list[Agent], title: str, max_turns: int,
                   model: str, topic_body: str) -> Session:
    """Create session directory, transcript, notes dirs, MISSION.md copy."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sessions_dir = project_root / "sessions"
    work_dir = sessions_dir / f"{slug}-{timestamp}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Store a pointer to the mission source instead of copying.
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

    # Write initial transcript header
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

    orch_log.touch()
    return session


def resume_session(work_dir: Path, agents: list[Agent]) -> tuple[Session, dict]:
    """Load existing session from state.json, rebuild history if needed.
    Returns (session, state_dict).
    """
    transcript = work_dir / "transcript.md"
    state_file = work_dir / "state.json"
    orch_log = work_dir / "orchestrator.log"
    utterances_dir = work_dir / "utterances"
    notes_dir = work_dir / "notes"

    utterances_dir.mkdir(exist_ok=True)
    for a in agents:
        (notes_dir / a.name).mkdir(parents=True, exist_ok=True)
    (notes_dir / "_operator").mkdir(parents=True, exist_ok=True)

    session = Session(
        work_dir=work_dir,
        transcript=transcript,
        state_file=state_file,
        orch_log=orch_log,
        utterances_dir=utterances_dir,
        notes_dir=notes_dir,
    )

    state = {}
    if state_file.exists():
        state = load_state(state_file)
        session.utterances = state.get("utterances", 0)
        session.last_speaker = state.get("last_speaker", "")
        session.consecutive_count = state.get("consecutive_count", 0)
        session.speakers_history = state.get("speakers_history", [])
        session.interventions = state.get("interventions", [])
        # Backward compat: rebuild from transcript for old state files.
        if not session.speakers_history and session.utterances > 0 and transcript.exists():
            for line in transcript.read_text(encoding="utf-8").splitlines():
                if line.startswith("### Turn "):
                    parts = line.split(" -- ")
                    if len(parts) >= 2:
                        session.speakers_history.append(parts[1].split()[0].strip())

    info(f"Resuming at turn {session.utterances + 1}, last speaker: {session.last_speaker}")
    return session, state


def update_state(session: Session, status: str, agents: list[Agent],
                 max_turns: int, model: str, mission_source: str) -> None:
    """Save session state to state.json."""
    state = {
        "utterances": session.utterances,
        "max_turns": max_turns,
        "status": status,
        "last_speaker": session.last_speaker,
        "consecutive_count": session.consecutive_count,
        "speakers_history": session.speakers_history,
        "agents": [a.name for a in agents],
        "model": model,
        "mission_source": mission_source,
        "interventions": session.interventions,
    }
    session.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def archive_outputs(work_dir: Path) -> str:
    """Archive closing.md and synthesis.md for --feedback runs.
    Returns archive timestamp.
    """
    archive_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    for fname in ("closing.md", "synthesis.md"):
        fpath = work_dir / fname
        if fpath.exists():
            stem = fpath.stem
            archived = fpath.with_name(f"{stem}-{archive_ts}.md")
            fpath.rename(archived)
            info(f"Archived {fname} -> {archived.name}")
    return archive_ts


# ---------------------------------------------------------------------------
# Transcript I/O
# ---------------------------------------------------------------------------

def append_agent_turn(session: Session, speaker: str, response: str,
                      action: str = "speak", task: dict | None = None) -> None:
    """Write utterance file + append to transcript."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = speaker.replace("/", "_")

    # Utterance file
    task_str = task.get("task", "") if task else ""
    (session.utterances_dir / f"{ts}-{safe_name}.md").write_text(
        f"# {speaker} -- Turn {session.utterances + 1}"
        + (f" (execute)\n\n**Task**: {task_str}\n\n" if action == "execute" else "\n\n")
        + f"{response}\n",
        encoding="utf-8",
    )

    # Transcript
    turn_time = datetime.now().strftime("%H:%M")
    with session.transcript.open("a", encoding="utf-8") as f:
        f.write(f"### Turn {session.utterances + 1} -- {speaker} [{turn_time}]"
                + (f" [execute]" if action == "execute" else "") + "\n"
                + (f"**Task**: {task_str}\n\n" if action == "execute" else "")
                + f"{response}\n\n---\n\n")


def append_orchestrator_turn(session: Session, pick_result: dict) -> None:
    """Write orchestrator utterance file."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    speaker = pick_result.get("speaker", "?")
    action = pick_result.get("action", "speak")
    reasoning = pick_result.get("reasoning", "")

    (session.utterances_dir / f"{ts}-host.md").write_text(
        f"# Orchestrator -- Turn {session.utterances + 1}\n\n"
        f"**Speaker picked**: {speaker}\n"
        f"**Action**: {action}\n"
        f"**Reasoning**: {reasoning}\n"
        + (f"**Task**: {pick_result.get('task', '')}\n" if action == "execute" else ""),
        encoding="utf-8",
    )


def append_verification(session: Session, turn_label: str, status: str,
                        details: str, attempt_label: str = "") -> None:
    """Write verification to transcript + notes/_verification/."""
    verify_notes = session.notes_dir / "_verification"
    verify_notes.mkdir(parents=True, exist_ok=True)

    suffix = f"-{attempt_label}" if attempt_label else ""
    (verify_notes / f"{turn_label}{suffix}.md").write_text(
        f"# Verification -- {turn_label}{' ' + attempt_label if attempt_label else ''}\n\n"
        f"**Status**: {status}\n"
        f"**Details**: {details}\n",
        encoding="utf-8",
    )

    with session.transcript.open("a", encoding="utf-8") as f:
        v_time = datetime.now().strftime("%H:%M")
        f.write(f"### Verification -- {turn_label}"
                f"{' ' + attempt_label if attempt_label else ''} [{v_time}]\n"
                f"**Status**: {status}\n"
                f"**Details**: {details}\n\n---\n\n")


def append_retry_turn(session: Session, speaker: str, response: str,
                      retry_num: int, task: dict) -> None:
    """Append retry execution response to transcript."""
    with session.transcript.open("a", encoding="utf-8") as f:
        r_time = datetime.now().strftime("%H:%M")
        f.write(f"### Turn {session.utterances} -- {speaker}"
                f" [execute retry {retry_num}]"
                f" [{r_time}]\n"
                f"**Task**: {task.get('task', '')}\n\n"
                f"{response}\n\n---\n\n")


# ---------------------------------------------------------------------------
# Transcript windowing
# ---------------------------------------------------------------------------

def get_transcript_context(transcript: Path, utterances: int,
                            recent_turns: int = 7) -> str:
    content = transcript.read_text(encoding="utf-8")
    if utterances <= recent_turns:
        return content

    turns = re.split(r'(?=^### Turn )', content, flags=re.MULTILINE)
    actual = [t for t in turns if t.startswith("### Turn ")]
    recent = actual[-recent_turns:]

    header_match = re.search(r'^## Discussion\s*$', content, re.MULTILINE)
    if header_match:
        header = content[:header_match.end()]
    else:
        header = content[:200]

    omitted = utterances - recent_turns
    return (f"{header}\n\n"
            f"[Turns 1-{omitted} omitted -- key findings are in notes/ folders]"
            f"\n\n{''.join(recent)}")


def truncate_transcript_for_closing(transcript: Path,
                                     keep_recent: int = 15) -> str:
    """Truncate transcript for closing summary, keeping structure and final positions."""
    content = transcript.read_text(encoding="utf-8")

    header_match = re.search(r'^## Discussion\s*$', content, re.MULTILINE)
    if not header_match:
        return content
    header = content[:header_match.end()]

    turn_blocks = re.split(r'(?=^### Turn )', content[header_match.end():],
                           flags=re.MULTILINE)
    turn_blocks = [t for t in turn_blocks if t.startswith("### Turn ")]

    if len(turn_blocks) <= keep_recent:
        return content

    agent_last: dict[str, int] = {}
    for i, block in enumerate(turn_blocks):
        m = re.match(r'### Turn \d+ -- (\S+)', block)
        if m:
            agent_last[m.group(1)] = i

    recent_start = len(turn_blocks) - keep_recent
    keep_indices = set(range(recent_start, len(turn_blocks)))
    for idx in agent_last.values():
        keep_indices.add(idx)

    parts = [header, "\n\n"]
    omitted = len(turn_blocks) - len(keep_indices)
    if omitted > 0:
        parts.append(f"[{omitted} earlier turns omitted "
                     f"-- agent notes contain full details]\n\n")

    for i, block in enumerate(turn_blocks):
        if i in keep_indices:
            parts.append(block)

    return "".join(parts)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state(state_file: Path) -> dict:
    return json.loads(state_file.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Operator intervention
# ---------------------------------------------------------------------------

def inject_operator_turn(session: Session, msg: str) -> None:
    """Inject an operator message as a turn in the transcript."""
    turn_num = session.utterances + 1
    turn_time = datetime.now().strftime("%H:%M")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")

    (session.utterances_dir / f"{ts}-operator.md").write_text(
        f"# [operator] -- Turn {turn_num}\n\n{msg}\n",
        encoding="utf-8",
    )

    with session.transcript.open("a", encoding="utf-8") as f:
        f.write(f"### Turn {turn_num} -- [operator] [{turn_time}]\n"
                f"{msg}\n\n---\n\n")

    op_notes = session.notes_dir / "_operator"
    op_notes.mkdir(parents=True, exist_ok=True)
    (op_notes / f"intervention-turn-{turn_num}.md").write_text(
        f"# Operator intervention (turn {turn_num})\n\n{msg}\n",
        encoding="utf-8",
    )

    session.utterances += 1
    session.last_speaker = "[operator]"
    session.speakers_history.append("[operator]")
    session.interventions.append({
        "turn": turn_num,
        "type": "inject",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    })

    ok(f"Intervention injected as turn {turn_num}")
