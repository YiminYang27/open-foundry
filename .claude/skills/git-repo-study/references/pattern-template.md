# Pattern Output Format

Use this format when writing `03-patterns.md` in Step 5.

---

## Transferable Patterns

For each pattern that can be adopted independently of the target repo:

```markdown
### {Pattern Name}

**Mechanism**: {2-3 sentences explaining how it works, with file path citations}

**Source**: `{file_path}` (line ~{N} if relevant)

**Adoption cost**: low | medium | high

**Prerequisite**: {What the user's repo needs for this pattern to work.
E.g. "Claude Code with .claude/skills/ directory" or "Git hooks support"}

**Example adaptation**:
{2-3 lines showing what the adopted version would look like in the user's repo}
```

---

## Non-Transferable Patterns

For each pattern tied to the target repo's specific context:

```markdown
### {Pattern Name}

**Why it doesn't transfer**: {One sentence explaining the dependency.
E.g. "Requires the repo's custom plugin loader which is not open-source"}
```

---

## Classification Criteria

A pattern is **transferable** when:
- It is a design principle or structural pattern, not a specific implementation
- It can be described without referencing the target repo's internal APIs
- The user's repo has (or can easily add) the prerequisites

A pattern is **non-transferable** when:
- It depends on the target repo's specific runtime, plugin system, or data format
- Adopting it would require importing the target repo as a dependency
- The cost of adaptation exceeds the cost of building from scratch
