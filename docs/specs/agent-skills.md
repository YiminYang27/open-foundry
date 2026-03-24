# Agent Skills Specification

Version: 1.0
Last updated: 2026-03-24

## Overview

Agent Skills are reusable, structured workflows for Claude Code and GitHub
Copilot. They follow the open
[Agent Skills specification](https://agentskills.io/specification) and
provide guided, multi-step processes for common tasks.

## File Location

```
.claude/skills/{skill-name}/
  SKILL.md                   # Required: skill definition
  references/                # Optional: format templates, reference docs
```

The `name` field in SKILL.md frontmatter must be lowercase with hyphens and
match the directory name.

## SKILL.md Format

### Frontmatter

```yaml
---
name: <skill-name>
description: <one-line description>
---
```

| Field | Required | Format | Description |
|-------|----------|--------|-------------|
| `name` | Yes | lowercase-hyphenated | Must match directory name |
| `description` | Yes | Single line | Trigger description for Claude Code skill matching |

The `description` field is critical -- it determines when Claude Code
activates the skill. Include trigger phrases that users would naturally say
(e.g., "analyze this repo", "create a role", "build a taskforce").

### Body

The body contains step-by-step instructions that Claude Code follows when
the skill is triggered. Each step uses `### Step N -- {Title}` headers.

Skills should:
- Follow steps in order
- Interact with the user at decision points (confirm understanding,
  present options, get approval)
- Read actual files before making claims (grounded, not from memory)
- Validate output before reporting completion

### References Directory

`references/` contains supporting documents the skill reads during
execution:
- Format templates (e.g., `role-format.md`, `mission-format.md`)
- Output structure templates (e.g., `pattern-template.md`)

These are referenced by relative path from the skill instructions.

## Current Skills

### build-taskforce

**Trigger**: `/build-taskforce`
**Purpose**: Guided assembly of a multi-agent discussion mission.

Steps:
1. Clarify the task (adaptive questioning, not fixed questionnaire)
2. Scan `roles/` for available agents, build factor-to-agent mapping
3. Address coverage gaps (may invoke `create-role` for new roles)
4. Select orchestrator from `roles/orchestrator/`
5. Confirm final taskforce with user
6. Generate `missions/{slug}/MISSION.md`
7. Validate (coverage, turn count, deliverable, file existence)
8. Report with run command

References: `references/mission-format.md`

### create-role

**Trigger**: `/create-role`
**Purpose**: Guided creation of a new agent role with overlap detection.

Steps:
1. Understand intent (2-3 rounds of adaptive questioning)
2. Check for overlap against existing roles in `roles/`
3. Generate role file with all required sections
4. Validate against quality checklist
5. Report with YAML snippet for mission files

References: `references/role-format.md`

### git-repo-study

**Trigger**: `/git-repo-study`
**Purpose**: Deep technical analysis of a Git repository.

Steps:
1. Scope the study (target URL/path, focus area, specific questions)
2. Clone to `sources/repos/{repo-name}`
3. Structural exploration (README, directory tree, file patterns, skills)
4. Design philosophy and architecture analysis
5. Domain-specific investigation (user's questions)
6. Key takeaways comparison (target repo vs current project)
7. Transferable patterns extraction
8. Integration plan with executable steps
9. Write 5 output files to `surveys/{repo-name}/`
10. Self-verify (citations, comparisons, completeness)

References: `references/pattern-template.md`

## Design Conventions

### Adaptive Questioning

Skills should not front-load a fixed questionnaire. Instead:
- Read the user's initial description
- Summarize understanding back to the user
- Ask only about gaps (2-3 questions per round max)
- Stop when enough specificity is gathered
- Skip rounds when the user's input already answers the questions

### Grounding

Skills must read actual files before making claims. This applies to:
- Scanning `roles/` for existing agents (not from a static list)
- Scanning `roles/orchestrator/` for available orchestrators
- Reading the current project state before comparisons
- Verifying file existence before referencing

### User Confirmation Gates

Major decisions require explicit user confirmation:
- Task understanding (Step 1 of build-taskforce)
- Agent panel composition
- New role creation
- Final mission before file generation

### File Generation

Skills that generate files must:
1. Create the file in the correct location
2. Validate against the format spec
3. Report the file path and a usage snippet
