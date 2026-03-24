# Role Format Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

Role files define agent personas used in `forge.py` discussions. Each role
represents a distinct analytical perspective with clear boundaries.

## File Location

```
roles/{category}/{name}.md
```

Categories are subdirectories under `roles/`. Current categories:
- `general/` -- cross-domain roles
- `software/` -- code analysis roles
- `finance/` -- financial analysis roles
- `orchestrator/` -- moderation strategies (separate spec, not agent roles)

New categories can be added by creating a subdirectory.

## Discovery

`forge.py` discovers roles by recursively searching `roles/` for
`{name}.md` files (excluding `orchestrator/`). No registry file is needed.

## Frontmatter Schema

```yaml
---
name: <identifier>
expertise: <one-line summary>
---
```

| Field | Required | Format | Description |
|-------|----------|--------|-------------|
| `name` | Yes | snake_case, no spaces | Must match filename without `.md` |
| `expertise` | Yes | Single line, plain text | Shown to orchestrator for speaker selection decisions |

Frontmatter is parsed with regex (flat key:value only). Do not use nested
structures, multi-line values, or quoted strings.

## Persona Body Structure

The markdown body after the closing `---` is injected as the agent's system
context. It must include these sections in order:

### 1. Core Identity (1-2 paragraphs)

Opens with "You are a ..." establishing the role's specialty and primary
question or perspective. Must include a clear differentiator -- what makes
this role distinct from adjacent expertise areas.

Requirements:
- State the primary question the role always asks
- Articulate what this role sees that no other role does
- Avoid generic descriptions ("expert in X") -- be specific about the lens

Example:
```
You are a software system architect who reads codebases structurally.
Your primary question is always: "What is unique about this repo's
architecture, and what would an AI agent get wrong if it assumed standard
framework behavior?"
```

### 2. Decision Criteria

Header: "When evaluating proposals, you consider:" or "you ask:"

3-5 bullet points defining the analytical framework the agent applies to
every claim or proposal it encounters. These shape every response.

### 3. Negative Space

Header: "What you are NOT:"

2-4 bullet points establishing explicit boundaries. Uses "You are not..."
or "You do not..." phrasing. Each bullet must reference which other role
owns the excluded territory.

This is the most important section for multi-agent coherence. Without it,
agents overlap and produce redundant responses.

### 4. Stall-Breaker

Header: "When the discussion stalls/gets abstract, you:"

1-2 sentences describing how this role contributes when the discussion
loses momentum. Provides a constructive fallback behavior.

### 5. Grounding Tendency

Woven throughout the persona (not necessarily a separate section). Defines
how the role anchors abstract discussions in concrete evidence:

| Role Type | Grounding Method |
|-----------|-----------------|
| Architect | Traces import graphs and dependency chains |
| API Explorer | Shows actual function signatures and exports |
| Example Explorer | Produces concrete code examples from real files |
| Critical Analyst | Constructs counter-examples |
| Finance roles | WebSearch for current data before any quantitative claim |

### 6. Evidence Methodology (domain-dependent)

Finance and data-dependent roles must include an explicit evidence protocol:
- SEARCH before citing any number
- Verify source and date
- Cross-check against second source when possible
- Flag unverifiable claims explicitly

## Quality Criteria

Before finalizing a role, verify ALL of:

- [ ] Clear specialty with differentiator (not just "expert in X")
- [ ] Decision criteria section ("When evaluating proposals...")
- [ ] Negative space section ("What you are NOT...")
- [ ] Stall-breaker section ("When the discussion stalls/gets abstract...")
- [ ] Grounding tendency present
- [ ] Complementary to existing roles (no major overlap)
- [ ] >= 150 words in persona body (enough for 30+ turn consistency)
- [ ] `name` is snake_case and matches the filename
- [ ] `expertise` is a concise one-line summary
- [ ] ASCII only (no emoji or special Unicode)

## Anti-Patterns

### Too Generic
"You are an expert in software engineering." -- gives the LLM no specific
lens. It will produce generic responses indistinguishable from base model
behavior.

### No Negative Space
Without "what you are NOT" the agent overreaches into other roles'
territory, producing redundant responses and blurring role boundaries.

### Overlapping with Existing Role
If a proposed role's expertise overlaps >= 70% with an existing role, it
produces repetitive discussion. Either narrow the new role or extend the
existing one.

### Too Short
A persona under 150 words cannot sustain consistent character across 30+
turns. The LLM fills gaps with generic behavior.

### Prescriptive Output Format
Do not bake specific output formats into the persona (e.g., "always respond
with a numbered list"). The persona defines perspective and judgment --
response format is controlled by the agent prompt in forge.py.
