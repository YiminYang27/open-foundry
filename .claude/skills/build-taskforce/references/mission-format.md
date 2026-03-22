# Mission File Format Specification

## File Location

`missions/{slug}.md` -- slug is lowercase-hyphenated (e.g. `gold-price-outlook.md`).

## Frontmatter Schema

```yaml
---
agents:
  - role: <name>          # Required. References roles/{category}/{name}.md
  - role: <name>
orchestrator: <name>      # Optional. References roles/orchestrator/{name}.md. Default: "default"
max_turns: <int>          # Optional. Default: 20
model: <string>           # Optional. sonnet/opus/haiku. Default: sonnet
---
```

## Body Structure

### 1. Title (required)

`# <Title>` -- one-line heading. Should be a specific question or thesis, not
a vague area.

Good: "Gold Price Outlook: 2026 H2 - 2027"
Bad: "Gold Discussion"

### 2. Framing Paragraph (required)

1-3 sentences that establish WHAT to discuss and WHY. Include scope boundaries
(timeframe, geography, asset class) so agents don't wander.

### 3. Key Factors / Questions (required)

Structured breakdown of what agents should investigate. Organized by domain
so each agent knows where to focus. Use `##` or `###` subsections.

Each factor should be:
- Specific enough to research (not "discuss the economy")
- Phrased as a question or evaluation target
- Relevant to the deliverable

### 4. Source References (optional, for code-related topics)

Absolute file paths to source code or reference documents. Agents have file
access via `--dangerously-skip-permissions` and can read these directly.

### 5. Deliverable (required)

Explicit description of what the discussion should produce. This shapes the
synthesizer's output and gives agents a target to work toward. Use a numbered
list of concrete output items.

## Quality Criteria

- [ ] Title is a specific question or thesis, not a vague area
- [ ] Scope is bounded (timeframe, geography, domain)
- [ ] Each agent has clear factors to investigate in their domain
- [ ] Deliverable is concrete and structured (not "discuss X")
- [ ] Agent composition covers all key factors without major gaps
- [ ] Orchestrator matches the discussion type
- [ ] max_turns is appropriate (10-15 for focused, 25-40 for deep analysis)

## Anti-Patterns

### Too Broad
"Discuss the global economy" -- no scope boundary, agents will produce
surface-level observations without depth.

### No Deliverable
Without an explicit deliverable section, agents discuss without converging.
The synthesizer has no target structure and produces a generic summary.

### Agent-Factor Mismatch
Listing factors no agent is equipped to address. Every key factor should have
at least one agent whose expertise covers it.

### Too Many Agents for Too Few Turns
6 agents with max_turns 10 means each agent speaks ~1.5 times. Deep discussion
needs at least 4-5 turns per agent. Rule of thumb: max_turns >= agents * 4.
