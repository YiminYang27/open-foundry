---
agents:
  - role: system_architect
  - role: llm_expert
  - role: convention_explorer
  - role: backend_engineer
  - role: database_engineer
  - role: critical_analyst
orchestrator: default
max_turns: 30
model: sonnet
---

# Should AI Coding Agents Replace Code Review?

AI coding agents (Claude Code, Cursor, GitHub Copilot) can now read
entire codebases, run tests, and propose changes autonomously. Some
teams are asking whether AI agents can replace human code review -- or
at least handle the bulk of it.

Evaluate this question honestly. Avoid both AI hype and knee-jerk
dismissal.

## Factors to evaluate

### What code review actually catches
- Logical errors and edge cases
- Architectural violations and hidden coupling
- Convention drift and style inconsistency
- Security vulnerabilities
- Knowledge transfer and shared understanding

### What AI agents are good at today
- Static analysis and pattern matching at scale
- Convention enforcement and style checking
- Test coverage gap identification
- Catching common bug patterns
- Speed and consistency (no reviewer fatigue)

### What AI agents struggle with
- Intent verification ("is this what we actually want to build?")
- Organizational context (why a decision was made, who needs to know)
- Novel architectural trade-offs with no clear pattern
- Subtle security implications that require threat modeling
- Mentorship and team knowledge building

### Practical considerations
- Cost and latency of AI review vs human review
- False positive rate and reviewer trust
- Integration into existing CI/CD workflows
- Liability and accountability when AI-approved code fails

## Deliverable

1. A clear position: replace, augment, or separate concerns
2. Specific breakdown of which review tasks AI handles well vs poorly
3. Recommended workflow for teams considering AI-assisted code review
4. Failure modes to watch for if teams over-rely on AI review
