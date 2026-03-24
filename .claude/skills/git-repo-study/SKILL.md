---
name: git-repo-study
description: Deep technical analysis of a Git repository. Use when the user wants to study, analyze, dissect, or understand a GitHub repo, or says things like "analyze this repo", "study this project", "what can we learn from this repo", "break down this codebase", "how does this project work". Always clones the target repo locally before analysis. Target must be a Git repository, not a generic folder.
---

# Repo Study

Perform a structured, evidence-based technical analysis of a target Git
repository. Produce a set of output files covering structure, architecture,
domain-specific findings, transferable patterns, and an integration plan.

Follow these steps in order.

### Step 1 -- Scope the Study

Before anything else, understand what the user wants to learn.

**1a. Get the target**: GitHub URL or local path (required).

**1b. Clarify the study focus**: Ask the user which angle they care about.
Present these options (one question, let them pick or combine):

- **Architecture & Design** -- how the project is structured, design
  philosophy, module boundaries, key abstractions
- **Source Code Deep-Dive** -- specific logic, algorithms, data flow,
  how a particular feature works end-to-end
- **Skill / Prompt Engineering** -- how the repo instructs AI agents,
  skill format, enforcement mechanisms, prompt patterns
- **Integration / Adoption** -- what patterns can be extracted and
  brought into the user's own project
- **Full Study** -- all of the above

The user's choice determines which phases to emphasize. For example,
"Source Code Deep-Dive" means Step 5 (domain questions) is the bulk of
the work; "Architecture & Design" means Steps 3-4 are the bulk.

**1c. Gather remaining parameters** (skip any already provided):

| Parameter | Required | Description |
|-----------|----------|-------------|
| **Purpose** | Yes | One sentence: what this repo does and why the user cares |
| **Questions** | Yes | 2-5 specific questions aligned with the chosen focus |
| **Language** | Yes | Ask the user which language to use for the output. Do NOT assume or default -- get an explicit answer. |

If the user's initial message already implies a focus (e.g. "how does
this repo handle auth?"), confirm it and derive the questions -- do not
re-ask what is already clear.

### Step 2 -- Clone to Local

**Always clone before analysis.** Local files enable Grep/Glob/Read which
are far superior to WebFetch for deep analysis.

If the user provided a URL:
```bash
git clone {URL} sources/repos/{repo-name}
```

If the user provided a local path that is already under `sources/repos/`,
use it directly. Otherwise clone/copy it into `sources/repos/`.

After cloning, set `REPO_ROOT` to the local path for all subsequent steps.
All file path citations in the output must be relative to `REPO_ROOT`.

### Step 3 -- Structural Exploration

Map the repo before analyzing anything.

1. Read the README fully. Extract: purpose, install instructions, core
   concepts, stated design philosophy.
2. Map the directory tree (2+ levels deep). Classify each directory:
   - Entry points (README, config, manifests, main scripts)
   - Core content (where the actual value lives)
   - Supporting infrastructure (CI, tests, docs, hooks)
3. Identify file format patterns: what types are used for config, content,
   automation? What is the internal structure of primary content files?
4. **Scan for AI agent skill definitions.** Skills may live in any of:
   - `skills/` or `skills/{name}/SKILL.md` (standalone skill repos)
   - `.claude/skills/` (Claude Code native)
   - `.github/skills/` (GitHub Copilot)
   - `.cursor/skills/` or `.cursor-plugin/`
   - Root-level `CLAUDE.md`, `GEMINI.md`, `.cursorrules`
   - `hooks/` (session hooks that inject context)

   If any skill files are found, treat them as high-priority analysis
   targets in Steps 4 and 5. Skill architecture is often the most
   transferable part of a repo.

### Step 4 -- Design Philosophy & Architecture

Answer these questions (cite file paths for each):

1. What is the author's stated design philosophy? What tradeoffs did they
   explicitly choose?
2. How is content organized -- flat vs hierarchical? What is the unit of
   composition?
3. What enforcement mechanisms exist? (hooks, validation, CI, prompt-level
   constraints)
4. What is the loading/discovery mechanism? How does the system find and
   activate its content at runtime?
5. What are the explicit quality gates?

### Step 5 -- Domain-Specific Investigation

Answer the user's specific questions from Step 1.

For each question:
- State the answer in 2-3 sentences
- Cite the specific file(s) that support the answer
- If the answer requires reading multiple files, trace the chain

### Step 6 -- Key Takeaways (Target vs Current Project)

Before extracting patterns, explicitly compare the target repo against
the current project. For each major design dimension, produce a side-by-side:

| Dimension | Target Repo | Current Project | Verdict |
|-----------|-------------|-----------------|---------|
| {e.g. "Skill format"} | {how target does it} | {how we do it} | Adopt / Adapt / Skip |

**Adopt** = target's approach is better, bring it in as-is.
**Adapt** = target has a useful idea but our context differs, take the
principle and reshape it.
**Skip** = we already do this equally well, or the approach doesn't fit.

For each Adopt/Adapt verdict, write a one-paragraph **Key Takeaway**
explaining: what we gain, what changes, and what risk exists.

Read the current project's structure (roles/, topics/, scripts/, .claude/skills/,
CLAUDE.md) before writing this comparison. Do NOT guess what the current
project has -- verify by reading files.

### Step 7 -- Transferable Patterns

Read `references/pattern-template.md` for the output format.

Separate what is reusable from what is repo-specific. For each transferable
pattern: name it, explain the mechanism with file citations, rate adoption
cost (low/medium/high), and state what the current project needs as
prerequisite. Reference the Key Takeaways from Step 6 to justify inclusion.

### Step 8 -- Integration Plan

Produce concrete, executable steps to adopt the transferable patterns.

Each step must be:
- A single action (create file X, edit file Y, run command Z)
- Completable in under 30 minutes
- Ordered by dependency
- Paired with a verification action

### Step 9 -- Write Output

Output directory is always `surveys/{repo-name}/` (relative to project root).
Create it if it does not exist. `{repo-name}` is the repo's directory name
(e.g. `superpowers`, `langchain`).

Write these files:

| File | Content | Max |
|------|---------|-----|
| `surveys/{repo-name}/01-structure.md` | Steps 3-4: directory tree, philosophy, architecture | 3000 words |
| `surveys/{repo-name}/02-analysis.md` | Step 5: domain-specific answers | 2500 words |
| `surveys/{repo-name}/03-takeaways.md` | Step 6: key takeaways comparison table + verdicts | 2000 words |
| `surveys/{repo-name}/04-patterns.md` | Step 7: transferable vs non-transferable | 2000 words |
| `surveys/{repo-name}/05-integration.md` | Step 8: step-by-step plan | 2000 words |

### Step 10 -- Self-Verify

Before reporting done, confirm ALL of:

- [ ] Directory tree was produced from actual file reads, not from memory
- [ ] Every architecture claim cites a specific file path
- [ ] Every domain question has a file path citation
- [ ] Key Takeaways table compared target repo against current project by reading BOTH codebases
- [ ] Each Adopt/Adapt verdict has a one-paragraph justification
- [ ] Each transferable pattern has a source file and adoption cost
- [ ] Each integration step has a verification command
- [ ] No unqualified hedging ("probably", "might", "should work")
- [ ] Output files are within word limits

## Constraints

These apply to ALL steps:

1. **Grounding**: Read actual files before making claims. Do NOT answer from
   training data. If using a local clone, prefer Grep for discovery.
2. **Citations**: Every technical claim must cite a file path. Uncited claims
   must be labeled `[UNVERIFIED]`.
3. **No hedging**: Do not use "probably", "might", "should work", "seems
   like". Either you verified it or you mark it `[UNVERIFIED]`.
4. **Direct style**: No filler, no pleasantries, no restating the question.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Analyzing via WebFetch without cloning first | Always `git clone` to `sources/repos/` first |
| Describing the repo from training data without reading it | Read README + key files first, then write |
| Listing directory tree from memory | Use `Glob **/*` or `ls -R` on local clone |
| Only checking `skills/` for skill files | Also check `.claude/skills/`, `.github/skills/`, `.cursor/`, root CLAUDE.md |
| Calling a pattern "transferable" without explaining how | Each pattern needs: mechanism + adoption cost + prerequisite |
| Integration steps that are vague suggestions | Each step = one action + one file path + one verify command |
| Skipping domain-specific questions to save time | Step 5 is the user's primary interest; never skip |
