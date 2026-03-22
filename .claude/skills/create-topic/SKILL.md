---
name: create-topic
description: Create a forum discussion topic file for the multi-agent discussion system. Use when the user wants to start a discussion, create a topic, set up a forum session, or says things like "create a topic", "I want to discuss...", "set up a discussion about...", "let's have the agents discuss...". Guides through question sharpening, agent selection, orchestrator choice, and deliverable definition.
---

# Create Topic

You are helping the user create a topic file for a multi-agent forum discussion.
A good topic produces deep, evidence-based discussion that converges on actionable
insights. A bad topic produces shallow agreement or aimless wandering.

Your job is to ensure the topic is sharp enough to drive depth, scoped enough to
prevent drift, and structured enough to produce a useful deliverable.

Follow these steps in order:

### Step 1 -- Understand What the User Wants to Learn

Users often describe topics vaguely ("let's discuss the economy"). Your job is to
probe until you have a topic that will drive deep discussion, not surface-level
observations.

**Round 1 -- Core question** (ask 1-2 questions, no more):

1. What specific question do you want answered? Not "what topic" but "what do
   you want to KNOW at the end that you don't know now?"
2. What is the scope? (timeframe, geography, asset class, system, etc.)

**Round 2 -- Sharpen for depth** (based on Round 1):

3. What are the key factors or dimensions to evaluate? (These become the
   structured subsections agents investigate.)
4. What would a useful output look like? A forecast? A comparison? A decision
   framework? A risk assessment? (This becomes the deliverable.)

**Round 3 -- If needed**:

5. Are there specific data sources, reports, or code paths the agents should
   examine?
6. Any constraints or assumptions to set up front?

**When to skip rounds**: If the user's initial message already contains a specific
question, scope, and factors, acknowledge what you understood and jump to
unanswered questions. But if the description is vague, probe first.

**When to stop asking**: You have enough when you can articulate:
- A one-sentence thesis or question (the title)
- A bounded scope (timeframe, domain, geography)
- 3+ structured factors to investigate
- A concrete deliverable definition

Summarize back to the user before proceeding.

### Step 2 -- Select Agents

Scan the `roles/` directory at the project root to discover all available roles
and orchestrators. For each `.md` file found (recursively), read its YAML
frontmatter to extract `name` and `expertise`. Group by subdirectory category
(e.g. `general/`, `software/`, `finance/`, `orchestrator/`). This is the live
catalog -- do NOT rely on any static list.

Based on the topic's key factors, recommend an agent composition:

1. **Map factors to roles**: each key factor should have at least one agent whose
   expertise covers it. Flag any factor that no existing role can address.
2. **Ensure tension**: include at least one "thesis tester" role (critical_analyst,
   quant_engineer) to prevent unchallenged consensus.
3. **Avoid bloat**: prefer 4-6 agents. More than 7 dilutes each agent's airtime.
   Only add an agent if it covers a factor no other agent can.
4. **Suggest missing roles**: if the topic needs a perspective no existing role
   covers, tell the user and suggest creating one with `/create-role`.

Present the recommended panel to the user with a brief justification for each.

### Step 3 -- Select Orchestrator and Parameters

Based on the topic type:

- **General analysis/brainstorming**: `default` orchestrator
- **Financial/quantitative analysis**: `finance_moderator` (evidence gating)
- **If no orchestrator fits**: suggest creating one, or use `default`

Recommend `max_turns` based on: agents * 5 for deep discussion, agents * 3
for focused discussion. Round to nearest 5.

Recommend `model`: `sonnet` for most topics, `opus` for topics requiring
exceptional reasoning depth.

### Step 4 -- Generate Topic File

Read `references/topic-format.md` for the exact format spec.

Generate the topic file with:

1. **Frontmatter**: agents, orchestrator, max_turns, model
2. **Title**: specific question or thesis as `# heading`
3. **Framing paragraph**: 1-3 sentences establishing scope and purpose
4. **Key factors**: structured `##`/`###` subsections organized by domain,
   each containing 3-5 specific evaluation points or questions
5. **Source references** (if applicable): file paths or data sources
6. **Deliverable**: numbered list of concrete output items the discussion
   should produce

Write to `topics/{slug}.md` where slug is derived from the title.

### Step 5 -- Validate

1. Every key factor has at least one agent whose expertise covers it
2. max_turns >= number of agents * 4
3. Deliverable section exists and has concrete items
4. Title is a specific question or thesis, not a vague area
5. Orchestrator file exists at `roles/orchestrator/{name}.md`
6. All agent role files exist

### Step 6 -- Report

Show the user:

1. **File path**: where the topic was written
2. **Panel summary**: agent composition with brief role descriptions
3. **Run command**:
   ```bash
   ./scripts/forum.sh topics/{slug}.md
   ```
4. **Estimated discussion**: approximate turns and which agents cover which factors
