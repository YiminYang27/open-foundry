#!/usr/bin/env python3
"""
forge.py -- Multi-agent discussion orchestrator

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
import collections
from collections import Counter
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

if sys.stdout.isatty():
    RED    = '\033[0;31m'
    GREEN  = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE   = '\033[0;34m'
    CYAN   = '\033[0;36m'
    BOLD   = '\033[1m'
    NC     = '\033[0m'
else:
    RED = GREEN = YELLOW = BLUE = CYAN = BOLD = NC = ''


_session_log: Path | None = None
_pause_requested = False

def _log_to_file(plain_msg: str) -> None:
    if _session_log is not None:
        with open(_session_log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%H:%M:%S')} {plain_msg}\n")

def info(msg):  print(f"{BLUE}[INFO]{NC} {msg}"); _log_to_file(f"[INFO] {msg}")
def ok(msg):    print(f"{GREEN}[OK]{NC} {msg}"); _log_to_file(f"[OK] {msg}")
def warn(msg):  print(f"{YELLOW}[WARN]{NC} {msg}"); _log_to_file(f"[WARN] {msg}")
def err(msg):   print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr); _log_to_file(f"[ERROR] {msg}")
def fatal(msg): err(msg); sys.exit(1)

def speaker_line(name, text):
    print(f"{CYAN}[{name}]{NC} {text}"); _log_to_file(f"[{name}] {text}")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    name: str
    expertise: str
    persona: str


@dataclass
class Orchestrator:
    name: str
    pick_persona: str
    close_persona: str
    verify_persona: str = ""


@dataclass
class Session:
    work_dir: Path
    transcript: Path
    state_file: Path
    orch_log: Path
    utterances_dir: Path
    notes_dir: Path
    utterances: int = 0
    last_speaker: str = ""
    consecutive_count: int = 0
    speakers_history: list[str] | None = None
    interventions: list[dict] | None = None

    def __post_init__(self):
        if self.speakers_history is None:
            self.speakers_history = []
        if self.interventions is None:
            self.interventions = []


# ---------------------------------------------------------------------------
# Frontmatter parsing
# NOTE: Manual regex parsing -- only supports flat key:value pairs.
# Nested YAML, multi-line values, or quoted strings are not handled.
# This is intentional to avoid a pyyaml dependency (stdlib-only design).
# ---------------------------------------------------------------------------

def parse_frontmatter(path: Path) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Raises ValueError if no frontmatter."""
    content = path.read_text(encoding="utf-8")
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        raise ValueError(f"No YAML frontmatter found in {path}")
    return match.group(1), content[match.end():]


def parse_topic(path: Path) -> tuple[list[str], int, str, str, str, str]:
    """Parse topic file.
    Returns (agent_names, max_turns, model, orchestrator_name, title, body).
    """
    fm, body = parse_frontmatter(path)

    agents = []
    max_turns = 20
    model = "sonnet"
    orchestrator = "default"

    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("- role:"):
            agents.append(line.split(":", 1)[1].strip())
        elif line.startswith("max_turns:"):
            try:
                max_turns = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("model:"):
            model = line.split(":", 1)[1].strip()
        elif line.startswith("orchestrator:"):
            orchestrator = line.split(":", 1)[1].strip()

    title = "Untitled Discussion"
    for bline in body.splitlines():
        bline = bline.strip()
        if bline.startswith("# "):
            title = bline[2:].strip()
            break

    return agents, max_turns, model, orchestrator, title, body.strip()


def load_agent(roles_dir: Path, name: str) -> Agent:
    """Load an agent role file. Searches subdirectories if not found at top level."""
    candidate = roles_dir / f"{name}.md"
    if not candidate.exists():
        found = list(roles_dir.rglob(f"{name}.md"))
        if not found:
            fatal(f"Role file not found: {name}.md (searched in {roles_dir})")
        candidate = found[0]

    fm, body = parse_frontmatter(candidate)
    expertise = ""
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("expertise:"):
            expertise = line.split(":", 1)[1].strip()
            break

    return Agent(name=name, expertise=expertise, persona=body.strip())


def load_orchestrator(roles_dir: Path, name: str) -> Orchestrator:
    """Load an orchestrator role file and split into pick/close sections."""
    orch_file = roles_dir / "orchestrator" / f"{name}.md"
    if not orch_file.exists():
        fatal(f"Orchestrator role not found: {orch_file} (referenced as '{name}' in topic)")

    try:
        _, body = parse_frontmatter(orch_file)
    except ValueError:
        body = orch_file.read_text(encoding="utf-8")

    pick_section = ""
    close_section = ""
    verify_section = ""

    sections = re.split(r'(?=^## )', body, flags=re.MULTILINE)
    for section in sections:
        if section.startswith("## Speaker Selection"):
            pick_section = re.sub(r'^## Speaker Selection\s*\n', '', section).strip()
        elif section.startswith("## Closing Summary"):
            close_section = re.sub(r'^## Closing Summary\s*\n', '', section).strip()
        elif section.startswith("## Verification"):
            verify_section = re.sub(r'^## Verification\s*\n', '', section).strip()

    return Orchestrator(name=name, pick_persona=pick_section,
                        close_persona=close_section, verify_persona=verify_section)


# ---------------------------------------------------------------------------
# Claude subprocess
# ---------------------------------------------------------------------------

def call_claude(prompt: str, model: str, skip_perms: bool = False,
                dry_run: bool = False, label: str = "",
                timeout: int = 600, max_retries: int = 3) -> str:
    # timeout=600: agents with WebSearch/file access need up to 10 min.
    # Orchestrator calls should override with timeout=120.
    if dry_run:
        info(f"[DRY RUN] {label} prompt ({len(prompt)} chars)")
        return ""

    # Pass prompt via stdin to avoid OS ARG_MAX limit on long prompts
    cmd = ['claude', '-p', '-', '--model', model]
    if skip_perms:
        cmd.append('--dangerously-skip-permissions')

    for attempt in range(max_retries):
        try:
            # start_new_session isolates child from parent's process group
            # so Ctrl+\ (SIGQUIT) only reaches forge.py, not the claude subprocess.
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=timeout,
                                    start_new_session=True)
        except subprocess.TimeoutExpired:
            warn(f"{label} timed out after {timeout}s (attempt {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2)
            continue

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if attempt < max_retries - 1:
            warn(f"{label} call failed (exit {result.returncode}), retrying... (attempt {attempt + 1}/{max_retries})")
            time.sleep(2)
        else:
            warn(f"{label} call failed after {max_retries} attempts (exit {result.returncode})")

    return ""


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
    return f"{header}\n\n[Turns 1-{omitted} omitted -- key findings are in notes/ folders]\n\n{''.join(recent)}"


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
        parts.append(f"[{omitted} earlier turns omitted -- agent notes contain full details]\n\n")

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
# Orchestrator
# ---------------------------------------------------------------------------

def orchestrator_pick(session: Session, agents: list[Agent], orch: Orchestrator,
                      agent_list_str: str, max_turns: int, model: str,
                      dry_run: bool,
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

    prompt = f"""You are the orchestrator of a structured forum discussion.

Agents in this forum:
{agent_list_str}
YOUR ORCHESTRATION STRATEGY:
{orch.pick_persona}

- Turn {session.utterances + 1} of {max_turns}
{speaker_stats}{recent_decisions}
TRANSCRIPT (recent turns):
{transcript_ctx}

Do NOT use any tools. Do NOT read any files. Respond with ONLY JSON
(no markdown fences, no explanation):
{{"speaker": "<name>", "reasoning": "<one sentence>"}}
or
{{"speaker": "CONSENSUS", "reasoning": "<summary of agreement>"}}{action_block}"""

    if dry_run:
        info(f"[DRY RUN] Orchestrator prompt ({len(prompt)} chars)")
        return {"speaker": agents[0].name, "reasoning": "dry run"}

    raw = call_claude(prompt, model, skip_perms=True, label="Orchestrator",
                      timeout=120)
    if not raw:
        warn("Orchestrator returned empty response")
        return {"speaker": "FALLBACK", "reasoning": "orchestrator failed"}

    # Parse JSON -- handle markdown fences or extra text
    parsed = _extract_json(raw)

    # Log decision
    with session.orch_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(parsed) + "\n")

    return parsed


def _extract_json(text: str) -> dict:
    """Try to extract a JSON object from text, handling fences and extra content."""
    text = text.strip()
    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Markdown fences
    fenced = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    # First JSON object in text
    match = re.search(r'\{[^{}]*\}', text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {"speaker": "FALLBACK", "reasoning": "could not parse orchestrator response"}


# ---------------------------------------------------------------------------
# Agent speak
# ---------------------------------------------------------------------------

def agent_speak(session: Session, agent: Agent, topic_body: str,
                max_turns: int, model: str, dry_run: bool,
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

    prompt = f"""You are "{agent.name}" in a structured forum discussion.

YOUR ROLE AND PERSPECTIVE:
{agent.persona}

DISCUSSION TOPIC:
{topic_body}
{refs_block}
TRANSCRIPT SO FAR:
{transcript_ctx}

YOUR NOTES FOLDER: {session.notes_dir}/{agent.name}/
Write key findings, structured analysis, or reference material to your
notes folder as .md files. These persist across turns and are your
workspace for building up structured knowledge. Use descriptive filenames
(e.g. xds-access-patterns.md, api-surface.md).

IMPORTANT: After reading source files, append the file paths you read to
{session.notes_dir}/{agent.name}/files-read.md (one path per line). This helps other
agents know what has already been explored and avoid redundant work.

OTHER AGENTS' NOTES: {session.notes_dir}/
Read other agents' notes to see what they have already documented.
Check other agents' files-read.md to see what source files have already
been explored -- prioritize unread files over re-reading the same ones.

EVIDENCE-FIRST PROTOCOL:
You have access to WebSearch and WebFetch tools. When your response
involves quantitative claims (prices, rates, dates, statistics), you
MUST follow this sequence:
1. GATHER: Use WebSearch to find current, real data before making claims
2. VERIFY: Cross-check data against a second source if possible
3. REASON: Draw conclusions grounded in the verified data
4. CITE: State the specific number, date, and source in your response
NEVER fabricate or guess data points. If you cannot find reliable data
for a claim, explicitly say so rather than inventing numbers.

Do not include turn headers or speaker labels in your response.
Do not narrate your thinking process -- go straight to substance.
Turn {session.utterances + 1} of {max_turns}. Respond in 150-400 words.
Engage with what others said. Build on their points or challenge them
when you see a flaw. Do not agree without adding substance -- if you
cannot extend or challenge a point, skip it and address something else.
Be specific and concrete. ASCII only."""

    if dry_run:
        info(f"[DRY RUN] Agent {agent.name} prompt ({len(prompt)} chars)")
        return f"[dry run response from {agent.name}]"

    return (call_claude(prompt, model, skip_perms=True,
                        label=f"Agent {agent.name}")
            or "[agent declined]")


# ---------------------------------------------------------------------------
# Agent execute (implementation action)
# ---------------------------------------------------------------------------

def agent_execute(session: Session, agent: Agent, topic_body: str,
                  task: dict, max_turns: int, model: str, dry_run: bool,
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

    prompt = f"""You are "{agent.name}" executing a specific implementation task.

YOUR ROLE AND EXPERTISE:
{agent.persona}

MISSION CONTEXT:
{topic_body}
{refs_block}
YOUR TASK:
{task_desc}
{verify_block}
YOUR NOTES FOLDER: {session.notes_dir}/{agent.name}/
Write implementation notes, decisions made, and files changed to your notes
folder. Log what you implemented and any deviations from the task spec.
Append file paths you read to {session.notes_dir}/{agent.name}/files-read.md.

OTHER AGENTS' NOTES: {session.notes_dir}/
Read other agents' notes to understand what has been implemented so far.

EXECUTION LOG:
{transcript_ctx}

INSTRUCTIONS:
1. Read the spec/plan and understand the full context before coding
2. Implement the task by creating or modifying the specified files
3. After implementation, run any verification commands if specified
4. Write a brief summary of what you did, files changed, and any issues

Do not narrate your thinking process -- go straight to implementation.
Turn {session.utterances + 1} of {max_turns}. ASCII only.
Respond with a summary of what you implemented (100-300 words)."""

    if dry_run:
        info(f"[DRY RUN] Agent {agent.name} execute prompt ({len(prompt)} chars)")
        return f"[dry run execution from {agent.name}]"

    return (call_claude(prompt, model, skip_perms=True,
                        label=f"Agent {agent.name} (execute)",
                        timeout=600)
            or "[agent declined]")


# ---------------------------------------------------------------------------
# Verify task (after execute action)
# ---------------------------------------------------------------------------

def verify_task(session: Session, orch: Orchestrator, task: dict,
                agent_response: str, model: str, dry_run: bool) -> dict:
    """Verify a completed task using the orchestrator's verification persona."""

    if not orch.verify_persona:
        return {"status": "pass", "details": "no verification configured"}

    task_desc = task.get("task", "")
    verify_criteria = task.get("verify", "")

    prompt = f"""You are verifying a completed implementation task.

YOUR VERIFICATION STRATEGY:
{orch.verify_persona}

TASK THAT WAS ASSIGNED:
{task_desc}

AGENT'S RESPONSE:
{agent_response}

VERIFICATION CRITERIA:
{verify_criteria if verify_criteria else "(none specified -- check based on task description)"}

If verification commands were specified, run them now and report results.
Check that the implementation matches the task requirements.

Output ONLY JSON (no markdown fences, no explanation):
{{"status": "pass", "details": "<what was verified>"}}
or
{{"status": "fail", "details": "<what failed and why>"}}"""

    if dry_run:
        info(f"[DRY RUN] Verification prompt ({len(prompt)} chars)")
        return {"status": "pass", "details": "dry run"}

    raw = call_claude(prompt, model, skip_perms=True, label="Verification",
                      timeout=300)
    if not raw:
        return {"status": "pass", "details": "verification call failed, assuming pass"}

    return _extract_json(raw)


# ---------------------------------------------------------------------------
# Finalize and synthesize
# ---------------------------------------------------------------------------

def finalize(session: Session, orch: Orchestrator, model: str,
             consensus_status: str, dry_run: bool) -> None:

    transcript_content = session.transcript.read_text(encoding="utf-8")

    # Speaker breakdown (assumes snake_case agent names -- no spaces)
    counts: dict[str, int] = collections.Counter()
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

    summary_prompt = f"""You are the orchestrator closing a structured forum discussion.

{orch.close_persona}

TRANSCRIPT (truncated -- agent notes contain full details):
{truncated}"""

    if dry_run:
        summary = "[dry run closing summary]"
    else:
        summary = (call_claude(summary_prompt, model, skip_perms=True,
                               label="Closing summary")
                   or "[failed to generate closing summary]")

    # Write closing summary to independent file (overwrite on resume)
    closing_file = session.work_dir / "closing.md"
    closing_file.write_text(
        f"# Closing Summary\n\n"
        f"{summary}\n\n"
        f"## Statistics\n\n"
        f"- Total turns: {session.utterances}\n"
        f"- Speaker breakdown:\n{breakdown}\n"
        f"- Consensus: {consensus_status}\n"
        f"- Model: {model}\n"
        f"- Completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
        encoding="utf-8",
    )

    ok(f"Closing summary written to {closing_file}")


def synthesize(session: Session, roles_dir: Path, topic_body: str,
               model: str, dry_run: bool) -> None:
    print(f"\n{BOLD}--- Synthesizing reference document ---{NC}")

    synth_role_path = roles_dir / "general" / "synthesizer.md"
    if not synth_role_path.exists():
        warn(f"Synthesizer role not found at {synth_role_path} -- skipping synthesis")
        return

    try:
        _, synth_persona = parse_frontmatter(synth_role_path)
    except ValueError:
        synth_persona = synth_role_path.read_text(encoding="utf-8")

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

    synth_prompt = f"""You are the synthesizer for a completed forum discussion.

YOUR ROLE:
{synth_persona}

DISCUSSION TOPIC:
{topic_body}

NOTES DIRECTORY: {session.notes_dir}/
Read all agent notes listed below. These contain the structured findings.
Skip files-read.md (those are just file path logs).

Notes inventory:
{notes_inventory}

TRANSCRIPT: {session.transcript}
Read the transcript for the full discussion flow.

CLOSING SUMMARY: {session.work_dir / "closing.md"}
Read this for what was agreed, what was unresolved, and which agents
contributed what.
{prev_synthesis_block}
OUTPUT:
Write the synthesized reference document to: {synthesis_file}

This document is the PRIMARY deliverable of this discussion. A coding agent
will read ONLY this file to understand the topic. Make it self-contained,
structured for lookup, and include concrete code examples.

Do not narrate your thinking process. Just produce the document.
ASCII only."""

    if dry_run:
        info(f"[DRY RUN] Synthesizer prompt ({len(synth_prompt)} chars)")
        synthesis_file.write_text("[dry run synthesis]\n", encoding="utf-8")
        return

    info("Running synthesizer (this may take a few minutes)...")
    # NOTE: Does not use call_claude -- synthesizer writes synthesis.md
    # directly via file tools. capture_output=False lets user see progress.
    # Uses stdin to avoid OS ARG_MAX limit on long prompts.
    synth_timeout = 1800
    synth_retries = 3
    info(f"Synthesizer timeout: {synth_timeout}s x {synth_retries} retries")
    for attempt in range(synth_retries):
        # Clear partial synthesis from previous failed attempt
        if attempt > 0 and synthesis_file.exists():
            backup = synthesis_file.with_suffix(f".attempt{attempt}.md")
            synthesis_file.rename(backup)
            info(f"Moved partial synthesis to {backup.name}")
        try:
            result = subprocess.run(
                ['claude', '-p', '-', '--model', model,
                 '--dangerously-skip-permissions'],
                input=synth_prompt, capture_output=False, text=True,
                timeout=synth_timeout, start_new_session=True
            )
            if result.returncode == 0:
                break
            warn(f"Synthesizer exited with code {result.returncode} "
                 f"(attempt {attempt + 1}/{synth_retries})")
        except subprocess.TimeoutExpired:
            warn(f"Synthesizer timed out after {synth_timeout}s "
                 f"(attempt {attempt + 1}/{synth_retries})")
        if attempt < synth_retries - 1:
            info(f"Retrying synthesizer (attempt {attempt + 2}/{synth_retries})...")
            time.sleep(5)

    if synthesis_file.exists():
        lines = len(synthesis_file.read_text(encoding="utf-8").splitlines())
        ok(f"Synthesis written to {synthesis_file} ({lines} lines)")
    else:
        warn(f"Synthesizer did not produce {synthesis_file}")


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


def _inject_operator_turn(session: Session, msg: str) -> None:
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

    # Resolve paths
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    roles_dir = project_root / "roles"

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

    # Parse topic
    try:
        agent_names, max_turns, model, orch_name, title, topic_body = parse_topic(topic_path)
    except ValueError as e:
        fatal(str(e))

    # Apply overrides
    if args.max_turns is not None:
        max_turns = args.max_turns
    if args.model is not None:
        model = args.model

    if not agent_names:
        fatal("No agents defined in topic file")

    # Load roles
    info("Validating role files...")
    agents: list[Agent] = []
    for name in agent_names:
        agents.append(load_agent(roles_dir, name))
    ok(f"All {len(agents)} role files validated")

    # Load orchestrator
    orch = load_orchestrator(roles_dir, orch_name)
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
    global _session_log
    _session_log = work_dir / "runtime.log"

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
        _inject_operator_turn(session, args.feedback)
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
            finalize(session, orch, model, "unknown (synthesize-only mode)", args.dry_run)

        synthesize(session, roles_dir, topic_body, model, args.dry_run)

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
            session, agents, orch, agent_list_str, max_turns, model, args.dry_run,
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
            finalize(session, orch, model, "yes", args.dry_run)
            synthesize(session, roles_dir, topic_body, model, args.dry_run)
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
                                     max_turns, model, args.dry_run,
                                     mission_dir=topic_path.parent,
                                     recent_turns=recent_window)
        else:
            response = agent_speak(session, agent, topic_body, max_turns, model,
                                   args.dry_run, mission_dir=topic_path.parent,
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

        # Verify after execute actions (with retry loop)
        if action == "execute" and orch.verify_persona and not args.dry_run:
            max_task_retries = 3
            for retry_attempt in range(max_task_retries):
                attempt_label = (f" (retry {retry_attempt}/{max_task_retries})"
                                 if retry_attempt > 0 else "")
                print(f"{BOLD}--- Verifying task{attempt_label} ---{NC}")
                verification = verify_task(session, orch, pick_result, response,
                                           model, args.dry_run)
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
                        max_turns, model, args.dry_run,
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
        if not args.dry_run and _check_pause(session) and sys.stdout.isatty():
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
                _inject_operator_turn(session, msg)
            _update_state("running")

        print()

    # Max turns reached
    warn(f"Max turns ({max_turns}) reached without consensus")
    _update_state("completed")
    finalize(session, orch, model, "no (max turns reached)", args.dry_run)
    synthesize(session, roles_dir, topic_body, model, args.dry_run)

    print(f"\n{BOLD}=== Forum Complete ({session.utterances} turns, no consensus) ==={NC}")
    info(f"Transcript: {transcript}")
    synthesis = work_dir / "synthesis.md"
    if synthesis.exists():
        info(f"Synthesis: {synthesis}")


if __name__ == "__main__":
    main()
