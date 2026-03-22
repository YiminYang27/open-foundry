# open-foundry

An open-source multi-agent deliberation framework. Assemble a panel of
specialized AI agents, pose a question, and get a rigorously grounded
output where every claim is challenged, every domain is covered, and
the reasoning is preserved in a searchable transcript.

## Quick Start

### Prerequisites

- Python 3.12+
- [Claude CLI](https://docs.anthropic.com/en/docs/claude-cli) installed
  and available in PATH

### Run a Discussion

```bash
git clone https://github.com/YiminYang27/open-foundry.git
cd open-foundry

# Create a mission (or use the /build-taskforce skill in Claude Code)
# Then run:
./scripts/forge.py your-mission

# Options:
./scripts/forge.py your-mission --dry-run          # validate without calling Claude
./scripts/forge.py your-mission --model opus        # override model
./scripts/forge.py your-mission --max-turns 50      # override turn limit
./scripts/forge.py your-mission --resume your-mission-20260322-001929
```

The orchestrator script is stdlib-only Python -- no virtualenv or
`pip install` needed.

---

## How It Works

```
topic file  -->  orchestrator picks speaker  -->  agent speaks (claude -p)
                      ^                                |
                      |                                v
                      +--- transcript (appended) <-----+
                                                       |
                                                       v
                                                  notes/{agent}/

... repeat until CONSENSUS or max_turns ...

                      |
                      v
              synthesizer  -->  synthesis.md
```

Each agent call is **stateless**: the orchestrator injects recent transcript
turns, the agent's notes directory, and its role persona into a fresh
`claude -p` call. No agent carries memory between turns except through its
own notes folder.

---

## Directory Structure

```
open-foundry/
  roles/                Agent role definitions
    general/            Cross-domain roles
    software/           Code analysis roles
    finance/            Financial analysis roles
    orchestrator/       Orchestration strategies
  missions/             Mission definition files
  sessions/             Session output (git-ignored)
  scripts/              Orchestration scripts
  .claude/skills/       Agent Skills for Claude Code / Copilot
```

### `roles/` -- Agent Personas

Each file defines one agent's identity: what it knows, how it reasons,
and what it refuses to do. Organized by domain.

**Format**: `roles/{category}/{name}.md`

```yaml
---
name: macro_economist
expertise: global macroeconomic analysis, economic forecasting, central bank policy
---
```

The markdown body after the frontmatter is the persona -- it must include:

| Property | Purpose |
|----------|---------|
| **Differentiator** | What this role sees that no other role does |
| **Decision criteria** | What it optimizes for when evaluating claims |
| **Negative space** | What it explicitly does NOT do (prevents drift) |
| **Stall-breaker** | What it does when discussion goes in circles |

#### Included roles

**general/**: `critical_analyst` (assumption testing, counter-examples),
`synthesizer` (post-discussion synthesis -- auto-triggered, do not list
in topics)

**software/**: `system_architect`, `api_explorer`, `convention_explorer`,
`example_explorer`, `llm_expert`

**finance/**: `macro_economist`, `geopolitical_analyst`, `gold_analyst`,
`sellside_strategist`, `quant_engineer`, `technical_analyst`, `risk_modeler`

### `roles/orchestrator/` -- Moderation Strategies

Orchestrators are not discussion participants. They decide who speaks
next and when to declare consensus. Each file has two sections:

- **Speaker Selection** -- rules for picking the next speaker (coverage
  gaps, claim quality, rotation strategy, consensus criteria)
- **Closing Summary** -- structure for the post-discussion summary

| Orchestrator | Use Case |
|--------------|----------|
| `default` | General-purpose: balanced rotation, standard consensus |
| `finance_moderator` | Evidence quality gating, multi-domain coverage, structured bull/bear close |

### `missions/` -- Mission Definitions

Each mission is a directory containing a `MISSION.md` file and optional
reference materials.

**Structure**: `missions/{slug}/`

```
missions/gold-price-outlook/
  MISSION.md              # Mission definition (required)
  references/             # Supporting documents (optional)
```

**MISSION.md format**:

```yaml
---
agents:
  - role: macro_economist
  - role: gold_analyst
  - role: critical_analyst
orchestrator: finance_moderator   # optional; defaults to "default"
max_turns: 40
model: sonnet
---

# Discussion Title

Question body, key factors to evaluate, and deliverable specification.
```

### `sessions/` -- Discussion Output (git-ignored)

Each run creates a timestamped directory:

```
sessions/{mission-slug}-{timestamp}/
  transcript.md          Full discussion, all turns
  synthesis.md           Synthesized reference document (primary deliverable)
  closing.md             Orchestrator's closing summary with statistics
  mission.md             Copy of the MISSION.md used
  state.json             Turn counter, speaker history, status
  orchestrator.log       Orchestrator reasoning per speaker pick
  utterances/            Individual turn files (timestamped)
  notes/{agent}/         Per-agent working notes (persisted across turns)
```

The `notes/` directory is the agent's persistent memory within a session.
Agents use it to record search results, data snapshots, and working
hypotheses so they can build on prior reasoning without re-running
searches. Other agents can read each other's notes to avoid redundant work.

### `scripts/` -- Orchestration

`forge.py` is the main orchestrator. It parses the mission, loads
roles, runs the discussion loop, and produces the session output. It is
stdlib-only Python with no external dependencies.

It accepts a mission slug (looked up in `missions/`), a directory path,
or a direct path to MISSION.md:

```bash
./scripts/forge.py gold-price-outlook                       # slug
./scripts/forge.py missions/gold-price-outlook               # directory
./scripts/forge.py missions/gold-price-outlook/MISSION.md    # also works
```

### `.claude/skills/` -- Agent Skills

Reusable skill definitions that work with Claude Code and GitHub Copilot.
These follow the open [Agent Skills specification](https://agentskills.io/specification).

| Skill | Trigger |
|-------|---------|
| `create-role` | `/create-role` -- guided role creation with overlap detection |
| `build-taskforce` | `/build-taskforce` -- guided taskforce assembly with agent selection |

---

## Customization Guide

### Add a new domain

1. Create a directory under `roles/` (e.g. `roles/legal/`)
2. Add role files with clear negative space boundaries
3. Optionally create a domain-specific orchestrator in `roles/orchestrator/`
4. Create a topic file referencing your new roles

### Create roles and topics

Use the Agent Skills for guided workflows:

```
/create-role    # overlap checking, persona generation, quality validation
/build-taskforce   # question sharpening, agent selection, deliverable definition
```

Or create files manually following the formats above.

### Write a custom orchestrator

Copy `roles/orchestrator/default.md` and modify the Speaker Selection
and Closing Summary sections to enforce your domain's quality standards.

---

## Design Principles

**Stateless agents, persistent notes.** Each turn is a fresh LLM call.
Context continuity comes from injecting recent transcript and the
agent's notes directory. This keeps calls cheap and retryable.

**Negative space over expertise.** The most important part of a role is
what it refuses to do. This prevents overlap, forces collaboration, and
makes the orchestrator's routing decisions meaningful.

**Strategy as data.** Speaker rotation rules live in orchestrator files,
not in code. Different discussions need different moderation: evidence
gating for finance, divergent thinking for brainstorming, strict
grounding for code review.

**Synthesis is post-hoc.** The synthesizer runs after the discussion,
not during it. Agents argue freely; a separate pass produces the
structured reference document.

**Evidence-first protocol.** Finance roles must WebSearch before citing
any number. The `finance_moderator` orchestrator routes unsourced claims
to challengers. This prevents stale training-data assertions in domains
where recency matters.

---

## License

[MIT](LICENSE)
