# Architecture Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

open-foundry is a multi-agent deliberation framework. Specialized AI agents
are assembled into panels, debate a topic through a structured transcript,
and produce a synthesized reference document. The system is domain-general
and supports financial analysis, software codebase exploration, research
synthesis, and other structured reasoning tasks.

## Design Principles

### Stateless Agents, Persistent Notes

Each agent turn is a fresh `claude -p` subprocess call. No agent carries
in-process memory between turns. Context continuity comes from:

1. Recent transcript (last 7 turns, injected into the prompt)
2. Agent's notes directory (`notes/{agent}/` in the session)
3. Other agents' notes (readable, shared workspace)

This keeps calls cheap, retryable, and parallelizable in future versions.

### Negative Space Over Expertise

The most important part of a role definition is what it refuses to do. This:

- Prevents overlap between roles with adjacent expertise
- Forces genuine collaboration (no agent can answer everything alone)
- Makes the orchestrator's routing decisions meaningful
- Prevents agent drift across 30+ turn discussions

### Strategy as Data

Orchestration strategy (speaker selection rules, consensus criteria, closing
summary structure) lives in markdown files under `roles/orchestrator/`, not
in code. Different discussions need different moderation styles:

- Evidence gating for finance (unsourced claims get challenged)
- Divergent thinking for brainstorming
- Strict grounding for code review

### Synthesis is Post-Hoc

Agents argue freely during the discussion. A separate synthesizer pass runs
after the discussion ends to produce the structured reference document. This
separation prevents premature convergence and ensures the synthesizer has
the full transcript and all agent notes as input.

### Evidence-First Protocol

Agents with quantitative domains (finance, data analysis) must WebSearch
before citing any number. The `finance_moderator` orchestrator actively
routes unsourced claims to challengers. This prevents stale training-data
assertions in domains where recency matters.

## System Components

```
+------------------+       +-------------------+
|   missions/      |       |   roles/          |
|   {slug}/        |       |   general/        |
|     MISSION.md   +------>+   software/       |
|     references/  |       |   finance/        |
+--------+---------+       |   orchestrator/   |
         |                 +--------+----------+
         v                          |
+--------+--------------------------+----------+
|                                              |
|              forge.py (orchestrator)          |
|                                              |
|   1. Parse mission                           |
|   2. Load roles + orchestrator               |
|   3. Loop:                                   |
|      a. Orchestrator picks speaker (LLM)     |
|      b. Agent speaks (LLM)                   |
|      c. Append to transcript                 |
|      d. Update state                         |
|   4. Finalize (closing summary)              |
|   5. Synthesize (reference document)         |
|                                              |
+--------+-------------------------------------+
         |
         v
+--------+---------+
|   sessions/      |
|   {slug}-{ts}/   |
|     transcript   |
|     synthesis    |
|     closing      |
|     notes/       |
|     utterances/  |
|     state.json   |
+------------------+
```

## Directory Structure

```
open-foundry/
  roles/                  Agent role definitions (by domain)
    general/              Cross-domain roles (critical_analyst, synthesizer)
    software/             Code analysis roles
    finance/              Financial analysis roles
    orchestrator/         Orchestration strategies (not discussion participants)
  missions/               Mission definitions
    {slug}/               One directory per mission
      MISSION.md          Mission definition (required)
      references/         Supporting documents (optional)
  sessions/               Session output (git-ignored)
    {slug}-{timestamp}/   One directory per run
  scripts/                Orchestration scripts
    forge.py              Main orchestrator (stdlib-only Python)
  .claude/skills/         Agent Skills for Claude Code
  docs/                   Documentation
    specs/                Architecture and format specifications
```

## Data Flow

### Input

1. **Mission file** (`missions/{slug}/MISSION.md`): defines the question,
   agent panel, orchestrator, parameters, and deliverable
2. **Role files** (`roles/{category}/{name}.md`): agent personas with
   expertise, decision criteria, negative space, and stall-breaker
3. **Orchestrator file** (`roles/orchestrator/{name}.md`): speaker selection
   strategy and closing summary format
4. **Reference materials** (`missions/{slug}/references/`): optional
   supporting documents injected into agent prompts

### Processing

1. `forge.py` parses the mission, loads roles and orchestrator
2. The orchestrator (LLM call) picks a speaker based on transcript context,
   agent list, and its strategy
3. The chosen agent (LLM call) speaks, reading transcript context, its
   notes, and other agents' notes
4. The response is appended to the transcript and saved as an individual
   utterance file
5. Steps 2-4 repeat until CONSENSUS or max_turns
6. The orchestrator produces a closing summary
7. The synthesizer (a separate LLM call) reads all notes, transcript, and
   closing summary to produce the final reference document

### Output

- `transcript.md`: full discussion, all turns
- `synthesis.md`: primary deliverable, structured reference document
- `closing.md`: orchestrator's closing summary with statistics
- `notes/{agent}/`: per-agent working notes (persisted across turns)
- `utterances/`: individual turn files (timestamped)
- `state.json`: machine-readable session state
- `orchestrator.log`: orchestrator reasoning per speaker pick

## Role Catalog

### general/ (cross-domain)

| Role | Purpose |
|------|---------|
| `critical_analyst` | Stress-tests claims, finds unstated assumptions, constructs counter-examples |
| `synthesizer` | Post-discussion synthesis into structured reference document (auto-triggered, not listed in missions) |

### software/ (code analysis)

| Role | Purpose |
|------|---------|
| `system_architect` | Maps module boundaries, dependency graphs, identifies repo-specific architectural deviations |
| `api_explorer` | Catalogs importable interfaces, type definitions, export inventories |
| `convention_explorer` | Extracts enforced vs emergent coding conventions with confidence levels |
| `example_explorer` | Traces end-to-end call paths, produces concrete verified code examples |
| `llm_expert` | Evaluates LLM-executability of tasks, identifies ambiguity traps, designs decomposition |
| `frontend_engineer` | Evaluates component architecture, state management, rendering efficiency across frameworks |

### finance/ (financial analysis)

| Role | Purpose |
|------|---------|
| `macro_economist` | Concrete economic forecasts anchored in current data and historical precedent |
| `geopolitical_analyst` | Probabilistic event assessment with supply-chain transmission to markets |
| `gold_analyst` | Gold-specific fundamentals across all four identities (commodity, monetary, financial, safe-haven) |
| `sellside_strategist` | Cross-references and critically evaluates investment bank research |
| `quant_engineer` | Evaluates risk-adjusted returns, stress testing, position control |
| `technical_analyst` | Price structure analysis independent of fundamental narratives |
| `risk_modeler` | Probability calibration, correlation structure, tail risk quantification |

### orchestrator/ (moderation strategies)

| Orchestrator | Use Case |
|--------------|----------|
| `default` | General-purpose: balanced rotation, standard consensus detection |
| `finance_moderator` | Evidence quality gating, multi-domain coverage enforcement, structured bull/bear closing |

## Agent Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| `build-taskforce` | `/build-taskforce` | Guided mission assembly: clarify task, scan roles, fill gaps, select orchestrator, generate MISSION.md |
| `create-role` | `/create-role` | Guided role creation: overlap checking, persona generation, quality validation |
| `git-repo-study` | `/git-repo-study` | Deep repo analysis: structural exploration, architecture, domain questions, patterns, integration plan |

## Technology Constraints

- **Python 3.12+**, stdlib-only (no external dependencies)
- **Claude CLI** (`claude -p`) as the LLM interface
- **`--dangerously-skip-permissions`** for non-interactive agent execution
- **YAML frontmatter** parsed with regex (flat key:value only, no pyyaml)
- **ASCII only** in all git-tracked files (no emoji or special Unicode)
- **Prompt via stdin** to avoid OS ARG_MAX limits on long prompts
