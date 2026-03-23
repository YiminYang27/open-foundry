# Claude Code Agent Teams vs open-foundry -- Comparison Report

Date: 2026-03-23

## 1. Executive Summary

Claude Code Agent Teams and open-foundry both orchestrate multiple AI agents
working together, but they solve fundamentally different problems. Agent Teams
is a **task parallelism** tool for developers -- split coding work across
multiple Claude instances. open-foundry is a **structured deliberation**
framework -- force multiple perspectives to challenge each other and produce
rigorously grounded analysis.

They are not competitors. They occupy different quadrants of the multi-agent
design space.

---

## 2. Product Overview

### Claude Code Agent Teams

- **Vendor**: Anthropic (experimental feature, disabled by default)
- **Activation**: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- **Version requirement**: Claude Code v2.1.32+
- **Architecture**: Lead session + N teammate sessions, each an independent
  Claude Code instance with its own context window
- **Communication**: Direct messaging (message/broadcast), shared task list
  with file-lock-based claiming
- **Display**: In-process (Shift+Down to cycle) or split-pane (tmux/iTerm2)
- **Pricing**: Claude subscription + token cost scales linearly with teammates

### open-foundry

- **License**: MIT, open source
- **Dependencies**: Python 3.12+ stdlib only, Claude CLI in PATH
- **Architecture**: Single Python orchestrator (`forge.py`) spawning
  sequential `claude -p` subprocess calls. One agent speaks per turn.
- **Communication**: Indirect -- agents read recent transcript (windowed to
  last 7 turns) and each other's `notes/` folders
- **State**: Fully stateless agent calls. Persistence via notes/ and
  transcript files on disk
- **Pricing**: Free (pay only for underlying LLM API usage)

---

## 3. Detailed Comparison

### 3.1 Coordination Model

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Parallelism | True parallel -- teammates run concurrently | Strictly sequential -- one agent per turn |
| Communication | Direct messaging + broadcast between teammates | Indirect via transcript + notes/ folder |
| Task management | Shared task list with dependency tracking and file-lock claiming | Orchestrator decides next speaker; no explicit task decomposition |
| Human interaction | User can message any teammate at any time | Currently fully autonomous once started (--interactive proposed) |
| Coordination overhead | High (each teammate = full context window) | Low (one subprocess at a time) |

### 3.2 Agent Identity and Role Boundaries

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Role definition | Natural language in spawn prompt, ad-hoc | Structured .md files with frontmatter (name, expertise) |
| Negative space | Not formalized -- relies on prompt phrasing | **Explicit** -- each role declares what it refuses to do |
| Role reusability | One-off per session | Persistent role library organized by domain (finance/, software/, general/) |
| Overlap prevention | No structural mechanism | Negative space boundaries enforce division of labor |

This is open-foundry's most significant design advantage. In Agent Teams,
nothing stops a "security reviewer" teammate from also commenting on
performance. In open-foundry, a macro_economist structurally cannot make
trading recommendations because its persona explicitly forbids it.

### 3.3 Orchestration Strategy

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Who decides next action | Lead session (Claude instance) | Dedicated orchestrator LLM call with strategy file |
| Strategy customization | Natural language instructions to lead | Swappable orchestrator .md files (default, finance_moderator) |
| Evidence gating | Not built in | finance_moderator enforces: unsourced claims trigger challenger agents |
| Consensus detection | No formal mechanism | Orchestrator can return CONSENSUS to end discussion |
| Anti-loop guard | No built-in protection | Same agent 3x consecutive -> forced rotation |
| Fallback on failure | Teammate stops; lead may not notice | Round-robin fallback + JSON parse error handling |

### 3.4 Auditability and Reproducibility

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Transcript | Terminal output per teammate (not structured) | Structured transcript.md with turn headers and timestamps |
| Decision log | No dedicated log | orchestrator.log -- JSON record of every speaker pick with reasoning |
| Per-turn archival | No | Individual utterance files in utterances/ with timestamps |
| Agent working memory | Context window (volatile) | notes/{agent}/ on disk (persistent, inspectable) |
| Session resume | **Not supported** for in-process teammates | Full resume via --resume flag + state.json |
| Post-mortem analysis | Difficult -- must reconstruct from terminal scrollback | Every prompt can be reconstructed from transcript + notes |

This is another area where open-foundry is categorically stronger. Every
decision the orchestrator made, every agent's response, every note written --
all on disk in plain markdown. You can audit why the discussion converged or
diverged by reading files, not by replaying terminal sessions.

### 3.5 Synthesis and Deliverables

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Post-discussion synthesis | Lead "synthesizes findings" -- no structured process | Dedicated synthesizer role runs after discussion ends |
| Synthesizer role | Lead does everything | Independent agent that reads all notes + transcript + closing summary |
| Deliverable quality bar | Unspecified | "A coding agent reading ONLY this file should produce correct code on first attempt" |
| Closing summary | No formal structure | Orchestrator generates structured closing with consensus/bull/bear/risks |

### 3.6 Environment and Tool Access

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| File system access | Full (each teammate is a Claude Code session) | Via `claude -p --dangerously-skip-permissions` subprocess |
| Web search | Not available (Claude Code has no WebSearch) | **Available** -- agents use WebSearch/WebFetch via Claude CLI |
| Terminal commands | Full | Full (via Claude CLI) |
| MCP servers | Supported | Not directly (inherits Claude CLI's MCP config) |
| Hooks | TeammateIdle, TaskCompleted hooks available | Not available |

### 3.7 Cost and Token Efficiency

| Dimension | Agent Teams | open-foundry |
|-----------|-------------|--------------|
| Concurrent token usage | N context windows active simultaneously | 1 context window at a time |
| Context accumulation | Each teammate accumulates full conversation history | Stateless -- each call gets only recent 7 turns + notes |
| Typical session cost | High (3-5 teammates x full context each) | Moderate (sequential calls, windowed context) |
| Cost predictability | Hard to predict (depends on teammate activity) | Predictable (max_turns x avg cost per call) |

---

## 4. Use Case Fitness

### Where Agent Teams excels

- **Parallel code implementation**: 3 teammates each building a separate
  module simultaneously
- **Multi-hypothesis debugging**: competing theories tested in parallel,
  teammates actively disprove each other
- **Parallel code review**: security, performance, test coverage reviewers
  working simultaneously
- Tasks where **speed** matters more than structured reasoning

### Where open-foundry excels

- **Complex analytical questions** requiring multiple domain perspectives
  (financial forecasting, architectural decisions, research synthesis)
- **Evidence-gated discussions** where unsourced claims must be challenged
- Situations requiring **full auditability** of reasoning process
- Domains where **role boundary enforcement** prevents echo-chamber agreement
- Producing **structured reference documents** as primary deliverable
- When **cost control** matters -- sequential execution is inherently cheaper

### Neither tool is good for

- Real-time interactive pair programming (both have latency)
- Tasks requiring a single unified context (both split context across agents)

---

## 5. Architectural Lessons from Agent Teams for open-foundry

### 5.1 Direct inter-agent messaging (worth considering)

Agent Teams allows teammates to message each other directly. open-foundry's
current indirect communication (read transcript + notes) works but introduces
latency -- an agent can only respond to another's point in its next turn.

**Assessment**: The current model is actually a feature, not a bug. Forced
asynchronous communication through transcript creates a natural "cooling"
effect that prevents agents from getting stuck in rapid back-and-forth
arguments. This mirrors real panel discussion dynamics where a moderator
controls who speaks next.

### 5.2 Shared task list with dependencies (not relevant)

Agent Teams uses a task list with dependency tracking. This makes sense for
parallel implementation but does not map to deliberation, where the "task" is
a single discussion that unfolds organically.

### 5.3 Plan approval mode (worth adapting)

Agent Teams can require teammates to plan before implementing. A variant
for open-foundry: the orchestrator could require an agent to submit a "brief"
(what it intends to argue) before its full response, with the orchestrator
able to redirect if the brief overlaps with ground already covered.

### 5.4 Hooks for quality gates (worth implementing)

TeammateIdle and TaskCompleted hooks are valuable for enforcing quality. An
equivalent for open-foundry: a post-turn hook that evaluates whether the
agent's response cited sources (for finance discussions), with automatic
re-routing to critical_analyst if unsourced claims appear.

---

## 6. Key Takeaways

1. **Different tools for different jobs.** Agent Teams parallelizes coding
   tasks. open-foundry structures adversarial deliberation. Comparing them
   directly is like comparing a build system to a code review tool.

2. **open-foundry's moat is structured deliberation.** Negative space design,
   evidence gating, swappable orchestration strategies, and full auditability
   are things Agent Teams does not attempt. This is the differentiation to
   lean into.

3. **open-foundry's weakness is model lock-in.** Currently hardcoded to
   `claude -p`. Supporting API backends with user-provided tokens would
   unlock the largest potential user base (see separate backend architecture
   proposal).

4. **Stateless-by-design is an underrated advantage.** Agent Teams teammates
   accumulate context and cannot resume after crash. open-foundry's stateless
   calls + disk persistence means every session is fully resumable and every
   prompt is reconstructible. This matters for regulated industries.

5. **Agent Teams is experimental; open-foundry is functional.** Agent Teams
   requires manual flag activation, has known limitations around session
   resumption and cleanup, and is labeled experimental. open-foundry's core
   loop works reliably today.
