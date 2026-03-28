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
# Transcript windowing
# ---------------------------------------------------------------------------

def get_transcript_context(transcript: Path, utterances: int,
                            recent_turns: int = 7) -> str:
    content = transcript.read_text(encoding="utf-8")
    if utterances <= recent_turns:
        return content

    # Split on turn headers, keep last N
    turns = re.split(r'(?=^### Turn )', content, flags=re.MULTILINE)
    actual = [t for t in turns if t.startswith("### Turn ")]
    recent = actual[-recent_turns:]

    # Extract header up to and including ## Discussion
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
    """Truncate transcript for closing summary, keeping structure and final positions.

    Keeps: full header, each agent's last utterance, last N turns in full.
    keep_recent default 15: covers ~2 full rounds for a typical 6-8 agent panel,
    ensuring the closing summary sees the convergence phase. Callers can override
    for smaller/larger panels.
    """
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

    # Find each agent's last turn
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

    # Persist as a note so it survives transcript windowing
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
