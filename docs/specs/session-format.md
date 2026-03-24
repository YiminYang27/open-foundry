# Session Format Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

Sessions are the output of a `forge.py` run. Each session is a timestamped
directory containing the full discussion record, agent notes, and the
synthesized deliverable.

## Directory Structure

```
sessions/{slug}-{timestamp}/
  MISSION.md             Copy of the source mission (with source path comment)
  transcript.md          Full discussion, all turns
  synthesis.md           Synthesized reference document (primary deliverable)
  closing.md             Orchestrator's closing summary with statistics
  state.json             Machine-readable session state
  orchestrator.log       Orchestrator reasoning per speaker pick (JSONL)
  utterances/            Individual turn files
    {ts}-host.md         Orchestrator pick decisions
    {ts}-{agent}.md      Agent responses
  notes/                 Per-agent working notes
    {agent}/             One directory per agent
      *.md               Agent's working notes (free-form)
      files-read.md      Log of source files the agent has read
```

Sessions are git-ignored.

## File Formats

### MISSION.md

A copy of the source mission file, prepended with a comment identifying the
source path:

```
<!-- source: /path/to/missions/{slug}/MISSION.md -->
{original MISSION.md content}
```

### transcript.md

```markdown
# Discussion: {title}

> Started: {YYYY-MM-DD HH:MM}
> Agents: {comma-separated agent names}
> Max turns: {N}
> Model: {model}

## Topic
{mission body}

## Discussion

### Turn 1 -- {agent_name} [{HH:MM}]
{agent response}

---

### Turn 2 -- {agent_name} [{HH:MM}]
{agent response}

---
```

Turn headers follow the pattern `### Turn {N} -- {agent_name} [{HH:MM}]`.
The agent name is extracted from this header for speaker history tracking.

### closing.md

```markdown
# Closing Summary

{orchestrator-generated summary following the orchestrator's close_persona}

## Statistics

- Total turns: {N}
- Speaker breakdown:
- {agent}: {count} turns
- ...
- Consensus: {yes | no (max turns reached)}
- Model: {model}
- Completed: {YYYY-MM-DD HH:MM}
```

### synthesis.md

The primary deliverable. Written by the `synthesizer` role after the
discussion ends. Structure varies by mission deliverable definition but
follows the synthesizer's principles:

- Structured for lookup (ctrl-F), not sequential reading
- Tables for registries and catalogs
- Code blocks for exact syntax
- Preserves exact strings verbatim
- Flags unresolved items in a dedicated section

### state.json

```json
{
  "utterances": 28,
  "max_turns": 30,
  "status": "completed",
  "last_speaker": "example_explorer",
  "consecutive_count": 1,
  "speakers_history": ["system_architect", "api_explorer", ...],
  "agents": ["system_architect", "api_explorer", ...],
  "model": "sonnet",
  "mission_source": "/path/to/missions/{slug}/MISSION.md"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `utterances` | int | Number of completed turns |
| `max_turns` | int | Maximum allowed turns |
| `status` | string | `starting`, `running`, `completed`, `interrupted` |
| `last_speaker` | string | Name of the last agent who spoke |
| `consecutive_count` | int | How many times the last speaker spoke consecutively |
| `speakers_history` | string[] | Ordered list of all speakers |
| `agents` | string[] | List of agents in the panel |
| `model` | string | LLM model used |
| `mission_source` | string | Absolute path to the source mission file |

### orchestrator.log

One JSON object per line (JSONL format). Each line records an orchestrator
speaker selection decision:

```json
{"speaker": "macro_economist", "reasoning": "Need macro context before gold-specific analysis"}
{"speaker": "critical_analyst", "reasoning": "Unsourced CPI claim needs challenging"}
{"speaker": "CONSENSUS", "reasoning": "All agents converged on base case with supporting evidence"}
```

### utterances/

Individual turn files, named with timestamp and speaker:

- `{YYYYMMDD-HHMMSS}-host.md` -- orchestrator decisions
- `{YYYYMMDD-HHMMSS}-{agent_name}.md` -- agent responses

### notes/{agent}/

Per-agent working notes directory. Created empty at session start. Agents
write markdown files to this directory during their turns:

- Free-form `.md` files for analysis, data snapshots, working hypotheses
- `files-read.md` -- convention for logging source file paths read by the
  agent, so others can avoid redundant work

Notes persist across turns and are readable by all agents. This is the
primary mechanism for cross-turn context continuity.

## Session Lifecycle

### States

```
starting -> running -> completed
                    -> interrupted (SIGINT/SIGTERM)
```

### Resume

`--resume {session-name}` restores a session from its `state.json`:

```bash
./scripts/forge.py {mission} --resume {slug}-{timestamp} --max-turns 50
```

Requirements for resume:
- Session directory must exist under `sessions/`
- `state.json` must be present
- The mission file must be provided (first argument)
- `--max-turns` should be increased if the original limit was reached
