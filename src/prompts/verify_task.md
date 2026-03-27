You are verifying a completed implementation task.

YOUR VERIFICATION STRATEGY:
{verify_persona}

TASK THAT WAS ASSIGNED:
{task_desc}

AGENT'S RESPONSE:
{agent_response}

VERIFICATION CRITERIA:
{verify_criteria}

If verification commands were specified, run them now and report results.
Check that the implementation matches the task requirements.

Output ONLY JSON (no markdown fences, no explanation):
{{"status": "pass", "details": "<what was verified>"}}
or
{{"status": "fail", "details": "<what failed and why>"}}