# Mission Format Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

Mission files define the question, agent panel, and deliverable for a
multi-agent discussion. Each mission is a self-contained directory.

## Directory Structure

```
missions/{slug}/
  MISSION.md              # Required: mission definition
  references/             # Optional: supporting documents
```

- **Slug**: lowercase-hyphenated (e.g. `gold-price-outlook`,
  `xds-data-node-usage`)
- **`forge.py` invocation**: `./scripts/forge.py {slug}`

## MISSION.md Format

### Frontmatter Schema

```yaml
---
agents:
  - role: <name>
  - role: <name>
orchestrator: <name>
max_turns: <int>
model: <string>
---
```

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `agents` | Yes | -- | List of agent roles. Each `- role: <name>` references `roles/{category}/{name}.md` |
| `orchestrator` | No | `default` | References `roles/orchestrator/{name}.md` |
| `max_turns` | No | `20` | Maximum number of agent utterances |
| `model` | No | `sonnet` | LLM model: `sonnet`, `opus`, or `haiku` |

Frontmatter is parsed with regex (flat key:value only). The `agents` list
is parsed by matching lines starting with `- role:`.

### Body Structure

#### 1. Title (required)

`# <Title>` -- a specific question or thesis, not a vague area.

Good: "Gold Price Forecast: 2026-2028"
Bad: "Gold Discussion"

#### 2. Framing Paragraph (required)

1-3 sentences establishing WHAT to discuss and WHY. Include scope
boundaries (timeframe, geography, asset class, system) so agents do not
wander.

#### 3. Key Factors / Questions (required)

Structured breakdown of what agents should investigate. Organized by domain
using `##` or `###` subsections so each agent knows where to focus.

Each factor should be:
- Specific enough to research (not "discuss the economy")
- Phrased as a question or evaluation target
- Relevant to the deliverable

#### 4. Source References (optional)

File paths to source code, reference documents, or files in the mission's
`references/` directory. Agents have file access via
`--dangerously-skip-permissions` and can read these directly.

`forge.py` automatically detects a non-empty `references/` directory and
adds a `REFERENCE MATERIALS` block to every agent prompt, pointing them to
its path. No manual configuration needed.

#### 5. Deliverable (required)

Explicit description of what the discussion should produce. This shapes the
synthesizer's output and gives agents a convergence target. Use a numbered
list of concrete output items.

## References Directory

`missions/{slug}/references/` is optional. When present and non-empty:

1. `forge.py` adds a `REFERENCE MATERIALS` block to every agent prompt
2. Agents can read files directly from this directory
3. Files are NOT copied into the session directory (to avoid duplication
   of large files)

Supported content: any file type agents can read (markdown, text, CSV,
JSON, source code, etc.)

## Quality Criteria

- [ ] Title is a specific question or thesis, not a vague area
- [ ] Scope is bounded (timeframe, geography, domain, system)
- [ ] Each agent has clear factors to investigate in their domain
- [ ] Deliverable is concrete and structured (not "discuss X")
- [ ] Agent composition covers all key factors without major gaps
- [ ] Orchestrator matches the discussion type
- [ ] max_turns >= agents * 4 (enough for each agent to speak 4+ times)

## Sizing Guidelines

| Discussion Type | Agents | max_turns | Model |
|-----------------|--------|-----------|-------|
| Focused analysis | 3-4 | 15-20 | sonnet |
| Deep multi-domain | 5-7 | 25-35 | sonnet |
| High-stakes reasoning | 5-8 | 35-50 | opus |

Rule of thumb: max_turns = agents * 5 for deep work, agents * 3 for
focused work (round to nearest 5).

## Anti-Patterns

### Too Broad
"Discuss the global economy" -- no scope boundary, agents produce
surface-level observations without depth.

### No Deliverable
Without a deliverable section, agents discuss without converging. The
synthesizer has no target structure and produces a generic summary.

### Agent-Factor Mismatch
Listing factors no agent is equipped to address. Every key factor should
have at least one agent whose expertise covers it.

### Too Many Agents for Too Few Turns
6 agents with max_turns 10 means each agent speaks ~1.5 times. Deep
discussion needs at least 4-5 turns per agent.
