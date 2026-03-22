---
name: build-taskforce
description: Build a taskforce for a multi-agent discussion or development session. Use when the user wants to start a discussion, assemble a panel, set up a team, or says things like "build a taskforce", "assemble a panel", "I want to discuss...", "set up a discussion about...", "let's have the agents discuss...", "create a topic". Guides through question sharpening, agent selection, orchestrator choice, and deliverable definition.
---

# Build Taskforce

You are helping the user build a taskforce for a multi-agent session.
A good taskforce produces deep, evidence-based output that converges on
actionable insights. A bad one produces shallow agreement or aimless wandering.

Your job is to clarify the task, assemble the right team, fill gaps, and
produce a mission file that drives focused, high-quality collaboration.

Follow these steps in order:

### Step 1 -- Clarify the Task

Let the user describe what they want in their own words. Do NOT front-load
a fixed questionnaire. Instead:

1. Read the user's initial description carefully.
2. **Summarize your understanding** back to them in 2-3 sentences:
   what you think the goal is, the scope, and the expected output.
3. **List what is still unclear** -- only ask about gaps. Common gaps:
   - Scope boundary (timeframe, domain, geography, system, etc.)
   - Key factors or dimensions to evaluate
   - What the deliverable should look like (forecast, comparison,
     decision framework, risk assessment, code, etc.)
   - Specific data sources, repos, or documents to examine
4. Wait for the user to confirm or correct your understanding.

**Adaptive questioning rules**:
- If the user's description is already detailed, acknowledge what you
  understood and ask only about missing pieces.
- If the description is vague, probe deeper -- but ask at most 2-3
  questions per round to avoid interrogation fatigue.
- **Stop when** you can articulate all of these:
  - A one-sentence thesis or question (becomes the title)
  - A bounded scope
  - 3+ structured factors to investigate
  - A concrete deliverable definition

Confirm with the user: "Here is my understanding of the task: [summary].
Is this correct?" Only proceed after confirmation.

### Step 2 -- Scan Roles and Recommend Agents

Scan the `roles/` directory at the project root to discover all available
roles. For each `.md` file found (recursively, excluding `orchestrator/`),
read its YAML frontmatter to extract `name` and `expertise`. Group by
subdirectory category (e.g. `general/`, `software/`, `finance/`). This is
the live catalog -- do NOT rely on any static list.

Based on the confirmed task, build a **factor-to-agent mapping table**:

```
Factor                     Agent              Status
---------------------------------------------------------
央行政策影響                macro_economist    [covered]
技術面分析                  technical_analyst  [covered]
供應鏈風險                  ???                [gap]
```

Rules for composing the panel:

1. **Every key factor needs coverage**: each factor should have at least
   one agent whose expertise addresses it. Mark uncovered factors as gaps.
2. **Ensure tension**: include at least one "thesis tester" role
   (critical_analyst, quant_engineer, or similar) to prevent unchallenged
   consensus.
3. **Avoid bloat**: prefer 4-6 agents. More than 7 dilutes each agent's
   airtime. Only add an agent if it covers a factor no other agent can.

Present the mapping table and recommended panel to the user with a brief
justification for each agent.

### Step 3 -- Address Gaps with New Roles

For each gap identified in the mapping table:

1. Propose a new role concept: suggested name, expertise summary, and why
   this perspective matters for the task.
2. Ask the user: **"Should I create this role?"**

**If yes**:
- Follow the `/create-role` skill workflow to create the role file.
- Complete the full role creation (overlap check, persona generation,
  validation) before continuing.
- After the role is created, add it to the taskforce panel.
- Continue to the next gap.

**If no**:
- Identify the closest existing agent who can partially cover this gap.
- Note in the mapping table: "[partially covered by {agent}]".
- Continue to the next gap.

After all gaps are resolved, proceed to the next step.

### Step 4 -- Select Orchestrator

Scan `roles/orchestrator/` for available orchestrators. Read each file's
frontmatter and body to understand its strategy.

Recommend an orchestrator based on the task type:
- **General analysis/brainstorming**: `default`
- **Financial/quantitative analysis**: `finance_moderator` (evidence gating)
- **If no orchestrator fits**: suggest creating one, or use `default`

Present the recommendation with a one-line justification.

### Step 5 -- Confirm Final Taskforce

Before generating any files, present the complete taskforce for user
approval:

1. **Agent panel** (with role and justification for each)
2. **Orchestrator** (with justification)
3. **Parameters**:
   - `max_turns`: agents * 5 for deep work, agents * 3 for focused work
     (round to nearest 5)
   - `model`: `sonnet` for most tasks, `opus` for tasks requiring
     exceptional reasoning depth
4. **Deliverable definition** (from Step 1)

Ask the user: "Does this taskforce look right? Any agents to add or remove?"

Only proceed after the user confirms.

### Step 6 -- Generate Mission File

Read `references/mission-format.md` for the exact format spec.

Generate the mission file with:

1. **Frontmatter**: agents, orchestrator, max_turns, model
2. **Title**: specific question or thesis as `# heading`
3. **Framing paragraph**: 1-3 sentences establishing scope and purpose
4. **Key factors**: structured `##`/`###` subsections organized by domain,
   each containing 3-5 specific evaluation points or questions
5. **Source references** (if applicable): file paths or data sources
6. **Deliverable**: numbered list of concrete output items the session
   should produce

Write to `missions/{slug}.md` where slug is derived from the title.

### Step 7 -- Validate

1. Every key factor has at least one agent whose expertise covers it
2. max_turns >= number of agents * 4
3. Deliverable section exists and has concrete items
4. Title is a specific question or thesis, not a vague area
5. Orchestrator file exists at `roles/orchestrator/{name}.md`
6. All agent role files exist

### Step 8 -- Report

Show the user:

1. **File path**: where the topic was written
2. **Panel summary**: final agent composition with role descriptions
3. **Run command**:
   ```bash
   ./scripts/forge.py missions/{slug}.md
   ```
4. **Estimated session**: approximate turns and factor-to-agent coverage
