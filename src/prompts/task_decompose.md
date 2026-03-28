You are decomposing discussion conclusions into implementation tasks.

YOUR VERIFICATION STRATEGY:
{verify_persona}

CLOSING SUMMARY:
{closing_summary}

AGENTS AVAILABLE:
{agent_list_str}

Decompose the conclusions into specific, actionable implementation tasks.
For each task, identify:
- The task description (specific enough to implement without ambiguity)
- The best-suited agent based on expertise
- Verification criteria (a command or check to confirm completion)
- Dependencies on other tasks (by index, 0-based)

Output ONLY JSON (no markdown fences):
{{"tasks": [
  {{"task": "<description>", "agent": "<name>", "verify": "<criteria>", "depends_on": []}},
  ...
]}}

Order tasks so dependencies come first. Maximum 10 tasks.
Keep tasks concrete and scoped -- each should be completable in one execution.