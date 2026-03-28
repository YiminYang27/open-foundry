---
name: create-role
description: Create a new forum discussion role for the multi-agent discussion system. Use when the user wants to create a role, add a discussion agent, define a new agent persona, or says things like "create a role", "new agent role", "add a discussion agent", "I need a role for...". Guides through overlap checking, persona generation with quality criteria (decision criteria, negative space, grounding tendency), and validation.
---

# Create Role

You are helping the user create a new role for the multi-agent discussion system.
Role files define agent personas used in `forge.py` discussions. A good role
needs a clear differentiator, decision criteria, negative space, and grounding
tendency -- without these, the agent drifts or overlaps with existing roles.

Follow these steps in order:

### Step 1 -- Understand Intent

Users often describe roles vaguely ("I want a security expert"). Your job is to
probe until you have enough specificity to write a role that won't drift. Do NOT
skip ahead to generation until you can answer all four questions below.

**Round 1 -- Initial questions** (ask 2-3 at a time, not all at once):

1. What perspective or domain should this role serve? What gap does it fill
   that existing roles don't cover?
2. What kind of discussions would this role participate in? Give an example
   topic or scenario.

**Round 2 -- Sharpen the differentiator** (based on Round 1 answers):

3. When two agents disagree, what would THIS role prioritize? What lens does
   it apply that others don't? (This becomes the decision criteria.)
4. What should this role explicitly NOT do? What adjacent territory should it
   leave to other roles? (This becomes the negative space.)

**Round 3 -- Grounding and category** (if not yet clear):

5. How does this role ground abstract claims -- what evidence does it reach
   for? (code, data, examples, literature, standards, user feedback, etc.)
6. What category should it go in? Existing: `general/`, `software/`. The user
   may propose a new category.

**When to skip rounds**: If the user's initial message already answers questions
from Round 1 and Round 2 clearly, acknowledge what you understood and jump to
the unanswered questions. Never re-ask what the user already specified. But if
the description is vague (e.g., "a security role"), do not skip -- probe first.

**When to stop asking**: You have enough when you can articulate:
- A one-sentence differentiator (what makes this role unique)
- 3+ decision criteria bullets
- 2+ negative space bullets
- A grounding tendency

Summarize your understanding back to the user before proceeding to Step 2.
Ask: "Does this capture what you had in mind, or should I adjust?"

### Step 2 -- Check for Overlap

Scan the `roles/` directory at the project root. For each `.md` file found
(recursively, across all category subdirectories), read its YAML frontmatter
to extract `name` and `expertise`. This is the live role catalog -- do NOT
rely on any static list.

Compare the user's description against each existing role:
- If an existing role has >= 70% overlap with what the user described, **warn them**.
  Explain what the existing role already covers and ask if they want to:
  (a) use the existing role as-is, (b) extend the existing role, or (c) proceed
  with a narrower focus for the new role.
- If partial overlap exists, suggest how to differentiate by narrowing the focus.
- If no significant overlap, proceed.

### Step 3 -- Generate Role File

Read `references/role-format.md` (relative to this skill's directory) for the
exact format spec and quality criteria.

Generate the role file following this process:

1. **Derive `name`**: snake_case identifier from the user's description. No spaces.
2. **Write `expertise`**: one-line summary for the orchestrator.
3. **Write persona body** with ALL required sections:
   - Core identity (1-2 paragraphs with clear differentiator)
   - "When evaluating proposals, you consider:" (3-5 bullet points)
   - "What you are NOT:" (2-4 bullet points establishing boundaries)
   - "When the discussion stalls, you:" (1-2 sentences)
   - Grounding tendency woven throughout

4. **Write the file** to `roles/{category}/{name}.md`

### Step 4 -- Validate

After writing the file, verify:

1. **Frontmatter**: `name` and `expertise` are both present
2. **Name match**: `name` field matches the filename (without .md)
3. **Word count**: persona body is >= 150 words
4. **Quality criteria**: run through the checklist from `references/role-format.md`:
   - Clear specialty with differentiator?
   - Decision criteria section present?
   - Negative space section present?
   - Stall-breaker section present?
   - Grounding tendency present?
   - Complementary to existing roles?

If any check fails, fix the issue before proceeding.

5. **Lint script**: Run the validation script to verify:
   `bash scripts/lint-roles.sh roles/{category}/{name}.md`
   If validation fails, fix the reported issues and re-run until it passes.

### Step 5 -- Report

Show the user:

1. **File path**: where the role was written
2. **Role summary**: name, expertise, category
3. **Mission YAML snippet**: how to reference this role in a mission file:

```yaml
agents:
  - role: {name}
```

4. **Note**: the role catalog is derived dynamically from `roles/` -- no
   separate registry file needs updating.

