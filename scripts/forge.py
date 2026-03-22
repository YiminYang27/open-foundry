#!/usr/bin/env python3
"""
forge.py -- Multi-agent discussion orchestrator

Runs a structured discussion between LLM agents with distinct
perspectives, moderated by an orchestrator that picks speakers
and detects consensus. All discussion is recorded to a readable
transcript.

Usage:
  ./scripts/forge.py <mission-file> [OPTIONS]

Arguments:
  <mission-file>   Path to a .md file with YAML frontmatter (agents, max_turns, model)

Options:
  --max-turns N   Override max utterances (default: from mission file or 20)
  --model MODEL   Override model for all claude -p calls
  --resume DIR    Resume from a previous run directory
  --dry-run       Print prompts without calling Claude
  --help          Show this help message

Examples:
  ./scripts/forge.py missions/gold-price-outlook.md
  ./scripts/forge.py missions/gold-price-outlook.md --max-turns 50 --model opus
  ./scripts/forge.py missions/gold-price-outlook.md --resume sessions/gold-price-outlook-20260322-001929
"""

import argparse
import collections
import json
import re
import shutil
import signal
import subprocess
import sys
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


def info(msg):  print(f"{BLUE}[INFO]{NC} {msg}")
def ok(msg):    print(f"{GREEN}[OK]{NC} {msg}")
def warn(msg):  print(f"{YELLOW}[WARN]{NC} {msg}")
def err(msg):   print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)
def fatal(msg): err(msg); sys.exit(1)

def speaker_line(name, text):
    print(f"{CYAN}[{name}]{NC} {text}")


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

    sections = re.split(r'(?=^## )', body, flags=re.MULTILINE)
    for section in sections:
        if section.startswith("## Speaker Selection"):
            pick_section = re.sub(r'^## Speaker Selection\s*\n', '', section).strip()
        elif section.startswith("## Closing Summary"):
            close_section = re.sub(r'^## Closing Summary\s*\n', '', section).strip()

    return Orchestrator(name=name, pick_persona=pick_section, close_persona=close_section)


# ---------------------------------------------------------------------------
# Claude subprocess
# ---------------------------------------------------------------------------

def call_claude(prompt: str, model: str, skip_perms: bool = False,
                dry_run: bool = False, label: str = "",
                timeout: int = 300) -> str:
    if dry_run:
        info(f"[DRY RUN] {label} prompt ({len(prompt)} chars)")
        return ""

    # Pass prompt via stdin to avoid OS ARG_MAX limit on long prompts
    cmd = ['claude', '-p', '-', '--model', model]
    if skip_perms:
        cmd.append('--dangerously-skip-permissions')

    for attempt in range(2):
        try:
            result = subprocess.run(cmd, input=prompt, capture_output=True,
                                    text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            warn(f"{label} timed out after {timeout}s")
            if attempt == 0:
                time.sleep(2)
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        if attempt == 0:
            warn(f"{label} call failed, retrying...")
            time.sleep(2)

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
                      dry_run: bool) -> tuple[str, str]:

    transcript_ctx = get_transcript_context(session.transcript, session.utterances)

    prompt = f"""You are the orchestrator of a structured forum discussion.

Agents in this forum:
{agent_list_str}
YOUR ORCHESTRATION STRATEGY:
{orch.pick_persona}

- Turn {session.utterances + 1} of {max_turns}
- Agent notes are at: {session.notes_dir}/ -- read them to understand earlier context

TRANSCRIPT (recent 7 turns):
{transcript_ctx}

Output ONLY JSON (no markdown fences, no explanation):
{{"speaker": "<name>", "reasoning": "<one sentence>"}}
or
{{"speaker": "CONSENSUS", "reasoning": "<summary of agreement>"}}"""

    if dry_run:
        info(f"[DRY RUN] Orchestrator prompt ({len(prompt)} chars)")
        return agents[0].name, "dry run"

    raw = call_claude(prompt, model, skip_perms=True, label="Orchestrator")
    if not raw:
        warn("Orchestrator returned empty response")
        return "FALLBACK", "orchestrator failed"

    # Parse JSON -- handle markdown fences or extra text
    parsed = _extract_json(raw)
    speaker = parsed.get("speaker", "FALLBACK")
    reasoning = parsed.get("reasoning", "")

    # Log decision
    with session.orch_log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(parsed) + "\n")

    return speaker, reasoning


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
                max_turns: int, model: str, dry_run: bool) -> str:

    transcript_ctx = get_transcript_context(session.transcript, session.utterances)

    prompt = f"""You are "{agent.name}" in a structured forum discussion.

YOUR ROLE AND PERSPECTIVE:
{agent.persona}

DISCUSSION TOPIC:
{topic_body}

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

    summary_prompt = f"""You are the orchestrator closing a structured forum discussion.

{orch.close_persona}

FULL TRANSCRIPT:
{transcript_content}"""

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
    try:
        subprocess.run(
            ['claude', '-p', '-', '--model', model,
             '--dangerously-skip-permissions'],
            input=synth_prompt, capture_output=False, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        warn("Synthesizer timed out after 600s")

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
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-agent discussion orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        add_help=True,
    )
    parser.add_argument("topic_file", help="Path to mission .md file")
    parser.add_argument("--max-turns", type=int, default=None,
                        help="Override max utterances")
    parser.add_argument("--model", default=None,
                        help="Override model (opus/sonnet/haiku)")
    parser.add_argument("--resume", default=None, metavar="DIR",
                        help="Resume from a previous session directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print prompts without calling Claude")
    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    roles_dir = project_root / "roles"

    topic_path = Path(args.topic_file)
    if not topic_path.is_absolute():
        topic_path = project_root / topic_path
    if not topic_path.exists():
        fatal(f"Topic file not found: {topic_path}")

    resume_dir = None
    if args.resume:
        resume_dir = Path(args.resume)
        if not resume_dir.is_absolute():
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
        slug = topic_path.stem
        sessions_dir = project_root / "sessions"
        work_dir = sessions_dir / f"{slug}-{timestamp}"
        work_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(topic_path, work_dir / "topic.md")

    transcript = work_dir / "transcript.md"
    state_file = work_dir / "state.json"
    orch_log = work_dir / "orchestrator.log"
    utterances_dir = work_dir / "utterances"
    notes_dir = work_dir / "notes"

    utterances_dir.mkdir(exist_ok=True)
    for a in agents:
        (notes_dir / a.name).mkdir(parents=True, exist_ok=True)

    session = Session(
        work_dir=work_dir,
        transcript=transcript,
        state_file=state_file,
        orch_log=orch_log,
        utterances_dir=utterances_dir,
        notes_dir=notes_dir,
    )

    def _update_state(status: str) -> None:
        # Assumes snake_case agent names -- no spaces
        speakers_history = []
        if session.transcript.exists():
            for line in session.transcript.read_text(encoding="utf-8").splitlines():
                if line.startswith("### Turn "):
                    parts = line.split(" -- ")
                    if len(parts) >= 2:
                        speakers_history.append(parts[1].split()[0].strip())
        state = {
            "utterances": session.utterances,
            "max_turns": max_turns,
            "status": status,
            "last_speaker": session.last_speaker,
            "consecutive_count": session.consecutive_count,
            "speakers_history": speakers_history,
            "agents": [a.name for a in agents],
            "model": model,
        }
        session.state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Initialize or resume
    if resume_dir and state_file.exists():
        state = load_state(state_file)
        session.utterances = state.get("utterances", 0)
        session.last_speaker = state.get("last_speaker", "")
        session.consecutive_count = state.get("consecutive_count", 0)
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

    # Banner
    print(f"\n{BOLD}=== Forum Discussion ==={NC}\n")
    info(f"Topic:     {title}")
    info(f"Agents:    {' '.join(a.name for a in agents)}")
    info(f"Max turns: {max_turns}")
    info(f"Model:     {model}")
    info(f"Output:    {work_dir}")
    if resume_dir:
        info(f"Resuming from turn {session.utterances + 1}")
    print()

    # Main loop
    agent_names_set = {a.name for a in agents}

    while session.utterances < max_turns:
        print(f"{BOLD}--- Orchestrator picking speaker (turn {session.utterances + 1}/{max_turns}) ---{NC}")

        speaker, reasoning = orchestrator_pick(
            session, agents, orch, agent_list_str, max_turns, model, args.dry_run
        )

        # Save orchestrator utterance
        orch_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        (utterances_dir / f"{orch_ts}-host.md").write_text(
            f"# Orchestrator -- Turn {session.utterances + 1}\n\n"
            f"**Speaker picked**: {speaker}\n"
            f"**Reasoning**: {reasoning}\n",
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

        # Anti-loop guard: same agent 3x consecutive -> force rotation
        if speaker == session.last_speaker:
            session.consecutive_count += 1
        else:
            session.consecutive_count = 1

        if session.consecutive_count >= 3:
            warn(f"Agent {speaker} picked 3x in a row, forcing rotation")
            speaker = next_round_robin(agents, speaker)
            session.consecutive_count = 1

        speaker_line(speaker, reasoning)

        # Find agent object
        agent = next((a for a in agents if a.name == speaker), agents[0])

        # Agent speaks
        response = agent_speak(session, agent, topic_body, max_turns, model, args.dry_run)
        if not response:
            response = "[agent declined]"

        # Save agent utterance
        agent_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_name = speaker.replace("/", "_")
        (utterances_dir / f"{agent_ts}-{safe_name}.md").write_text(
            f"# {speaker} -- Turn {session.utterances + 1}\n\n{response}\n",
            encoding="utf-8",
        )

        # Append to transcript
        turn_time = datetime.now().strftime("%H:%M")
        with transcript.open("a", encoding="utf-8") as f:
            f.write(f"### Turn {session.utterances + 1} -- {speaker} [{turn_time}]\n"
                    f"{response}\n\n---\n\n")

        session.utterances += 1
        session.last_speaker = speaker
        _update_state("running")

        ok(f"Turn {session.utterances}/{max_turns} complete ({speaker})")
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
