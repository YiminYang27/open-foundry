# CLAUDE.md

## Project Overview

open-foundry is an open-source multi-agent deliberation framework. Groups of
specialized AI agents are assembled into panels to analyze complex topics,
challenge each other's claims, and produce rigorously grounded outputs.

The system is domain-general -- it supports financial analysis, architectural
review, research synthesis, codebase exploration, and other structured
reasoning tasks. Each agent holds a distinct analytical perspective with
explicit negative space (what it refuses to do), forcing genuine collaboration
rather than echo-chamber agreement.

## Directory Structure

```
open-foundry/
  roles/
    general/            Cross-domain roles (critical_analyst, synthesizer)
    software/           Code analysis roles (system_architect, api_explorer, ...)
    finance/            Financial analysis roles (macro_economist, gold_analyst, ...)
    orchestrator/       Orchestration strategies (default, finance_moderator)
  missions/             Mission definitions (YAML frontmatter + question body)
  sessions/             Session output: transcript, notes, synthesis (git-ignored)
  scripts/              Orchestration scripts (forge.py)
  .claude/skills/       Agent Skills for guided creation workflows
```

## Running a Discussion

```bash
./scripts/forge.py missions/{slug}.md
./scripts/forge.py missions/{slug}.md --dry-run        # validate without running
./scripts/forge.py missions/{slug}.md --model opus
./scripts/forge.py missions/{slug}.md --resume sessions/{slug}-{timestamp}
```

Use `/build-taskforce` skill to set up a discussion or task. Use `/create-role`
skill to add new agent roles. See README.md for full documentation.

## Temporary Output

When you need to write throwaway or one-off files (scratch analysis,
debug dumps, intermediate results), write them to `.tmp/` inside this
project -- NOT to ~/tmp or /tmp. This keeps temporary output colocated
with the project and easy to find. The directory is git-ignored.

## Python

- Recommended version: **3.12+**
- The orchestrator script (`scripts/forge.py`) is stdlib-only -- no
  external dependencies. No virtualenv setup needed to run it.
- If future scripts add dependencies:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt
  ```

## Prerequisites

- **Claude CLI (`claude`)** must be installed and available in PATH.
  The orchestrator invokes `claude -p` with `--dangerously-skip-permissions`
  for non-interactive execution.

## Coding Conventions

- Git-tracked files must NOT contain emoji or special Unicode characters.
  Use plain ASCII alternatives (e.g. `[!]`, `[v]`, `[x]`).
- Role names use `snake_case`. Topic file slugs use kebab-case.
- YAML frontmatter in role/topic files is flat key-value only (parsed
  with regex, not a YAML library). Do not use nested structures, multi-line
  values, or quoted strings in frontmatter.
- Agent Skills follow the open [Agent Skills specification](https://agentskills.io/specification).
  The `name` field must be lowercase with hyphens and match the directory name.
  The `description` field is required.
