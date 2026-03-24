# Orchestration Engine Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

`forge.py` is the orchestration engine that runs multi-agent discussions.
It is stdlib-only Python 3.12+ with no external dependencies. The only
prerequisite is the `claude` CLI in PATH.

## Invocation

```bash
./scripts/forge.py <mission> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `<mission>` | Mission slug, directory path, or MISSION.md file path |

Resolution order for the mission argument:
1. As a slug: `missions/{slug}/MISSION.md`
2. As a directory: `{path}/MISSION.md`
3. As a file: `{path}` directly

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--max-turns N` | From mission file (or 20) | Override maximum utterances |
| `--model MODEL` | From mission file (or sonnet) | Override model (opus/sonnet/haiku) |
| `--resume SESSION` | None | Resume from session directory (name or path) |
| `--dry-run` | False | Print prompts without calling Claude |

## Discussion Loop

### Main Loop

```
while utterances < max_turns:
    1. Orchestrator picks speaker (LLM call)
    2. Handle special cases:
       - CONSENSUS -> finalize + synthesize -> exit
       - FALLBACK / unknown agent -> round-robin fallback
       - Same agent 3x consecutive -> forced rotation
    3. Agent speaks (LLM call)
    4. Save utterance file
    5. Append to transcript
    6. Update state
```

### Orchestrator Pick

The orchestrator receives:
- Agent list with expertise summaries
- Its orchestration strategy (`pick_persona` from orchestrator file)
- Current turn number and max turns
- Path to agent notes directory
- Recent transcript (last 7 turns)

Expected output: JSON object

```json
{"speaker": "<agent_name>", "reasoning": "<one sentence>"}
```

Or for consensus:

```json
{"speaker": "CONSENSUS", "reasoning": "<summary of agreement>"}
```

JSON extraction is tolerant: handles markdown fences, extra text, and
nested objects. Falls back to regex extraction of first `{...}` block.

### Agent Speak

Each agent receives:
- Its full persona (from role file body)
- The mission topic body
- Reference materials block (if `references/` is non-empty)
- Recent transcript (last 7 turns)
- Path to its notes directory
- Path to all agents' notes (shared workspace)
- Evidence-first protocol instructions
- Turn number and max turns
- Response constraints (150-400 words, ASCII only)

### Transcript Windowing

To manage context window size:
- First 7 turns: full transcript is injected
- After 7 turns: only the last 7 turns are injected, with a note:
  `[Turns 1-{N} omitted -- key findings are in notes/ folders]`

This is the main driver for agents to write and read notes.

## Safeguards

### Anti-Loop Guard

If the orchestrator picks the same agent 3 times consecutively, `forge.py`
forces a round-robin rotation to a different agent. This prevents the
orchestrator from fixating on one agent.

### Round-Robin Fallback

If the orchestrator returns an unrecognized agent name, `FALLBACK`, or
an empty response, the engine falls back to simple round-robin rotation
based on the agent list order.

### Retry Logic

`call_claude` retries once on failure (timeout or empty response) with a
2-second delay. After two failures, returns an empty string. The engine
substitutes `[agent declined]` for empty agent responses.

### Timeout

Default timeout per LLM call: 300 seconds (5 minutes).
Synthesizer timeout: 600 seconds (10 minutes).

### Graceful Shutdown

SIGINT (Ctrl+C) and SIGTERM trigger:
1. Save current state to `state.json` with status `interrupted`
2. Print resume command
3. Exit with code 130

## Finalization

After the loop ends (consensus or max_turns):

### Closing Summary

The orchestrator is called with:
- Its `close_persona` (from the Closing Summary section of the
  orchestrator file)
- The full transcript (no windowing)

Output is written to `closing.md` with statistics.

### Synthesis

The `synthesizer` role (from `roles/general/synthesizer.md`) is called
with:
- Its persona
- The mission topic body
- An inventory of all agent notes (file paths and sizes)
- Path to notes directory, transcript, and closing summary
- Instructions to write output to `synthesis.md`

The synthesizer runs with `capture_output=False` so the user can see
progress, and has a 10-minute timeout.

## Orchestrator File Format

Orchestrator files live at `roles/orchestrator/{name}.md`.

They are NOT discussion participants. They are split into two sections:

### Speaker Selection (`## Speaker Selection`)

Rules for picking the next speaker. Injected into the orchestrator's
prompt on every turn. Contains:
- General rotation and consensus rules
- Domain-specific priorities (e.g., evidence gating for finance)
- Coverage requirements (which domains must be heard)
- Consensus prerequisites (what must be established before declaring
  CONSENSUS)

### Closing Summary (`## Closing Summary`)

Structure for the post-discussion summary. Injected when generating the
closing summary after the loop ends. Defines:
- Summary structure and sections
- Word count guidance
- What to include (agreements, disagreements, next steps)
- Domain-specific closing requirements (e.g., bull/bear cases for finance)

## File Encoding

All files are read and written with UTF-8 encoding. All agent-generated
content is constrained to ASCII by the prompt instructions.
