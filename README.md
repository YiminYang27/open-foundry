# open-foundry

An open-source multi-agent deliberation framework. Assemble a panel of
specialized AI agents, pose a question, and get a rigorously grounded
output where every claim is challenged, every domain is covered, and
the reasoning is preserved in a searchable transcript.

## Why open-foundry?

When you ask Claude a complex question, you get an answer -- but you
cannot see how it got there. The internal reasoning is a black box. If
the conclusion is wrong, you have no way to trace which assumption
failed or which perspective was never considered.

Open-foundry makes the reasoning process **fully inspectable**. Every
agent is a stateless `claude -p` call, so all thinking must be
externalized into files that you can read, search, and audit:

```
sessions/gold-price-outlook-20260324/
  transcript.md        865 lines -- every turn attributed and timestamped
  orchestrator.log     52 entries -- why each speaker was chosen
  notes/
    macro_economist/   8 working notes across 7 turns of evolving analysis
    critical_analyst/  challenges, counter-examples, gap inventories
    risk_modeler/      probability trees rebuilt 3 times as inputs changed
    ...
  utterances/          100+ individual turn files
  state.json           full speaker history and session metadata
```

You can trace exactly how a conclusion was built, torn apart, and
rebuilt. When the `gold_analyst` claimed central bank buying proved
strong demand, the `critical_analyst` identified circular reasoning --
gold prices rising mechanically inflates the dollar-value metric. That
challenge is in the transcript, attributable to a specific agent at a
specific turn. In a single Claude session, that self-correction rarely
happens because one model tends to maintain internal consistency with
its own prior output.

### How it compares to Claude Code CLI

Each open-foundry agent is a full Claude Code instance -- it has access
to all native tools (Read, Write, Bash, WebSearch, ...), MCP servers,
Agent Skills, and plugins. The framework does not limit agent
capabilities; it adds structure on top of what `claude -p` already
provides.

| | Claude Code CLI | open-foundry |
|---|---|---|
| Interaction model | Synchronous -- human drives every turn | Autonomous -- agents run, human observes |
| Reasoning visibility | Internal (extended thinking is hidden) | External (transcript, notes, orchestrator log) |
| Multi-agent relationship | Parent delegates to children, summarizes results | Peers debate each other across multiple rounds |
| Quality control | Human judges the output | Built-in (evidence gating, thesis testers, negative space) |
| Intervention | Required every turn | Optional -- Ctrl+\ when you see something worth correcting |
| Output | An answer | An answer + the full audit trail of how it was reached |

**When to use Claude Code CLI directly**: You are the domain expert, you
know what to ask, and you want a fast answer or need to write code.

**When to use open-foundry**: The question is complex enough that you
want multiple perspectives to challenge each other autonomously, and you
need to inspect (or show others) how the conclusion was reached.

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
./scripts/forge.py your-mission --resume your-mission-20260322-001929 --synthesize-only

# Intervention controls (during a running discussion):
#   Ctrl+\          pause after current turn completes
#   touch PAUSE     pause from another terminal
```

The orchestrator script is stdlib-only Python -- no virtualenv or
`pip install` needed.

---

## How It Works

```
mission  -->  orchestrator picks speaker  -->  agent speaks (claude -p)
                      ^                                |
                      |                                v
                      +--- transcript (appended) <-----+
                      |                                |
                      |                                v
       [operator] ----+                          notes/{agent}/
       (Ctrl+\ to inject)

... agents run autonomously until CONSENSUS or max_turns ...
... human observes, intervenes only when needed ...

                      |
                      v
              synthesizer  -->  synthesis.md
```

Each agent call is **stateless**: the orchestrator injects recent transcript
turns, the agent's notes directory, and its role persona into a fresh
`claude -p` call. No agent carries memory between turns except through its
own notes folder.

**Human intervention** is pull-based. Agents run without human input by
default. To intervene mid-discussion:

- **Ctrl+\\** -- pause after the current turn finishes
- **`touch PAUSE`** -- pause from another terminal

When paused, you can type a message and press Enter to inject it as an
`[operator]` turn in the transcript. All agents see it in subsequent
turns, just like any other agent's utterance. Press Enter without typing
to resume without injection.

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

**Reasoning as artifact.** The stateless architecture forces all
thinking into external files -- transcript, notes, orchestrator log.
This is not a logging feature; it is a structural consequence. Because
no agent carries internal state between turns, every inference must be
written down to persist. The result is a fully auditable reasoning trail.

**Stateless agents, persistent notes.** Each turn is a fresh LLM call.
Context continuity comes from injecting recent transcript and the
agent's notes directory. This keeps calls cheap and retryable.

**Negative space over expertise.** The most important part of a role is
what it refuses to do. This prevents overlap, forces collaboration, and
makes the orchestrator's routing decisions meaningful.

**Autonomous by default, intervention by exception.** Agents run without
human input. The system never prompts, reminds, or asks the human to
act. If you want to intervene, you pull (Ctrl+\ or PAUSE file); the
system never pushes.

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

[Apache 2.0](LICENSE)
