# Role File Format Specification

## File Location

Role files live in `roles/{category}/{name}.md` where `{category}` is a
subdirectory like `general/` or `software/`.

## Frontmatter Schema

```yaml
---
name: <identifier>        # Required. snake_case, no spaces. Must match filename (without .md)
expertise: <one-line>     # Required. Shown to orchestrator for speaker selection
---
```

Both fields are required. The body below the frontmatter closing `---` is the
full persona prompt, injected as the agent's system context when it speaks.

## Persona Body Structure

The body should follow this structure (in order):

### 1. Core Identity (1-2 paragraphs)

Open with "You are a ..." that establishes the role's specialty and primary
question/perspective. Include a **clear differentiator** -- what makes this role
distinct from adjacent expertise areas.

Good: "You are a software system architect who reads codebases structurally.
Your key differentiator is spotting what is NOT standard."

Bad: "You are an expert in software." (too generic, no differentiator)

### 2. Decision Criteria ("When evaluating proposals, you consider/ask:")

3-5 bullet points that guide the agent's analytical lens. These shape every
response the agent gives -- they are the questions it applies to any proposal.

```markdown
When evaluating proposals, you consider:
- ...
- ...
- ...
```

### 3. Negative Space ("What you are NOT:")

Explicit boundaries that prevent the role from overreaching into other roles'
territory. 2-4 bullet points. Use "You are not..." or "You do not..." phrasing.

```markdown
What you are NOT:
- You are not contrarian for its own sake. If a proposal genuinely
  has no flaw, say so explicitly and explain why it is robust.
- You do not propose alternatives unless your critique reveals a gap
  that demands one. Your job is to test, not to design.
```

### 4. Stall-Breaker ("When the discussion stalls/gets abstract, you:")

1-2 sentences describing how this role contributes when the discussion loses
momentum. This gives the agent a constructive fallback behavior.

```markdown
When the discussion gets too abstract, you ground it: "Show me the
import graph. Which files actually call this?"
```

### 5. Grounding Tendency

Woven throughout the persona (not necessarily a separate section): how does this
role anchor abstract discussions in concrete evidence? Examples:
- Architect: traces import graphs and dependency chains
- API Explorer: shows actual function signatures and exports
- Example Explorer: produces concrete code examples
- Critic: constructs counter-examples

## Quality Criteria Checklist

Before finalizing a role, verify ALL of the following:

- [ ] Clear specialty with differentiator (not just "expert in X")
- [ ] Decision criteria section ("When evaluating proposals...")
- [ ] Negative space section ("What you are NOT...")
- [ ] Stall-breaker section ("When the discussion stalls/gets abstract...")
- [ ] Grounding tendency (how does this role anchor abstract discussions?)
- [ ] Complementary to existing roles (no major overlap)
- [ ] >= 150 words in persona body (enough for 30+ turn consistency)
- [ ] `name` is snake_case and matches the filename
- [ ] `expertise` is a concise one-line summary

## Anti-Patterns to Avoid

### Too Generic
"You are an expert in software engineering." -- gives the LLM no specific lens,
it will produce generic responses indistinguishable from base model behavior.

### No Decision Criteria
Without "when evaluating proposals, you consider..." the agent has no analytical
framework and will drift between turns, applying inconsistent reasoning.

### No Negative Space
Without "what you are NOT" the agent will overreach into other roles' territory,
producing redundant responses and blurring role boundaries.

### Overlapping with Existing Role
If a proposed role's expertise overlaps >= 70% with an existing role, it will
produce repetitive discussion. Either narrow the new role's focus or extend the
existing one.

### Too Short
A persona under 150 words cannot sustain consistent character across 30+ turns.
The LLM will fill gaps with generic behavior.

### Prescriptive Output Format
Do not bake specific output formats into the persona (e.g., "always respond with
a numbered list"). The persona defines perspective and judgment, not response
format -- that is controlled by the agent prompt in forge.py.
