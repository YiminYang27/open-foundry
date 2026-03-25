---
agents:
  - role: system_architect
  - role: llm_expert
  - role: backend_engineer
  - role: sre_ops_engineer
  - role: ai_ops_strategist
  - role: critical_analyst
orchestrator: default
max_turns: 60
model: opus
---

# xGuard Agentic Redesign: From Playbook Execution to Autonomous Operations

xGuard is an LLM-driven Kubernetes operations service that receives alerts from
monitoring systems and uses AI agents with MCP tools (kubectl, Prometheus, Loki)
to diagnose and remediate issues. The current architecture uses Google ADK with a
root agent that routes alerts via keyword matching to specialized agents, each
executing a fixed prompt-based playbook in a single LLM call. The goal of this
discussion is to redesign xGuard into a truly agentic operations service --
one that reasons autonomously, collaborates across diagnostic domains, learns
from past incidents, and evolves its capabilities over time.

Source code is at: sources/xhis-xguard-service/
Design spec is at: sources/xhis-xguard-service/docs/specs/xguard_design_spec.md
Superpowers multi-agent patterns study: surveys/superpowers/

## Current Architecture Assessment

Before proposing changes, agents MUST read and analyze the current codebase.
Key files to examine:

- `src/agents/xguard_root_agent.py` -- root agent with keyword-based routing
- `src/agents/alert_task_agent.py` -- base alert agent (single LLM call pattern)
- `src/agents/resource_alert_agent.py` -- specialized agent example (inherits base)
- `src/prompts/alert_task_agent_prompts.py` -- fixed prompt/playbook
- `src/prompts/resource_alert_agent_prompts.py` -- specialized prompt example
- `src/tools/` -- MCP tool integrations (kubectl, prometheus, ansible)
- `src/services/xguard_task_service.py` -- task orchestration service
- `src/routes.py` -- FastAPI endpoints
- `docs/specs/xguard_design_spec.md` -- original design spec

### Questions for current architecture analysis:
- What are the specific limitations of the current single-call agent pattern?
- Where does the keyword-based routing fail (false classifications, unknown types)?
- How are MCP tools currently organized and could they be shared across agents?
- What is the current error handling and recovery model?

## Multi-Agent Collaboration Architecture

### Agent Topology
- What should the agent graph look like? Options include: linear pipeline
  (triage -> diagnose -> remediate), hierarchical (controller + workers),
  or dynamic DAG based on alert complexity.
- How do agents share diagnostic context? Should there be a shared scratchpad,
  event stream, or structured handoff protocol?
- When should multiple agents work on the same alert (e.g., metrics agent +
  logs agent in parallel), and how do they merge findings?

### Reasoning Patterns
- How should agents implement multi-step reasoning? Consider ReAct (reason +
  act loops), chain-of-thought with tool use, and hypothesis-driven
  investigation.
- How does the system decide investigation depth? A simple CPU spike might
  need 2 steps; a cascading failure across services might need 20.
- How should the system handle conflicting evidence from different tools
  (e.g., Prometheus says healthy but logs show errors)?

## Autonomous Reasoning Capabilities

### Dynamic Tool Selection
- How should agents decide which MCP tools to use, rather than following a
  fixed checklist? What heuristics or strategies guide tool selection?
- How does the system avoid wasteful tool calls (querying irrelevant metrics)
  while not missing critical evidence?

### Hypothesis-Driven Diagnosis
- How can agents formulate and test hypotheses rather than following a linear
  checklist? E.g., "If this is an OOM issue, I expect to see memory growth
  in these metrics" -> test -> confirm/reject -> next hypothesis.
- How does the system know when it has enough evidence to act vs. when it
  needs to keep investigating?

### Confidence and Uncertainty
- How does the system express confidence in its diagnosis? When should it
  say "I am 90% certain this is an OOM" vs. "I have three hypotheses"?
- How does confidence level affect the automation boundary -- high confidence
  enables auto-remediation, low confidence triggers human review?

## Learning and Evolution

### Case Memory Architecture
- How should resolved incidents be stored for future reference? What is the
  schema for a "case record" (alert signature, diagnostic path, root cause,
  remediation, outcome)?
- How does the system retrieve relevant past cases when a new alert arrives?
  Vector similarity? Structured matching? Hybrid?

### Knowledge Accumulation
- How does the system build a growing knowledge base of: common failure
  patterns, effective diagnostic sequences, environment-specific quirks?
- How do we prevent knowledge rot -- outdated patterns that no longer apply
  after infrastructure changes?

### Feedback Loops
- When a human corrects the agent's diagnosis or overrides its action, how
  does that correction flow back into the system?
- How do we measure system improvement over time? What metrics distinguish
  "getting smarter" from "getting more complex"?

## Operational Safety and Control

### Action Classification
- Which K8S operations are safe to auto-execute (read-only queries, pod
  restart of a single crashlooping pod) vs. require human approval (scale
  changes, deployment rollbacks, node cordoning)?
- How should the safety policy be encoded -- hardcoded in code, configurable
  per-environment, or LLM-assessed per-situation?

### Blast Radius Control
- How does the system limit the scope of automated actions? Rate limiting,
  namespace isolation, dry-run modes?
- What happens when an automated action makes things worse? Automatic
  rollback? Alert escalation? Circuit breaker?

### Approval and Audit
- What is the approval workflow for high-risk actions? Synchronous human
  approval? Time-bounded auto-approval? Multi-level approval?
- How is every action logged for post-incident audit? What metadata is
  captured (reasoning chain, confidence, tool outputs, human approvals)?

## Migration Strategy

### Incremental Path
- How do we migrate from the current Google ADK architecture incrementally,
  without a big-bang rewrite?
- Which component should be upgraded first for maximum impact with minimum
  risk? (e.g., replace keyword routing with LLM-based triage first?)
- How do we run old and new agent patterns side-by-side during migration?

### Technology Choices
- Should we stay on Google ADK or consider alternatives (LangGraph,
  CrewAI, custom framework, pure prompt-based like Superpowers)?
- What are the tradeoffs of each approach for this specific use case
  (K8S ops, MCP tools, async processing, multi-pod deployment)?

## Deliverable

The discussion should converge on a concrete architectural redesign document
containing:

1. **Target architecture diagram** -- agent topology, data flow, tool
   integration, human interaction points
2. **Agent role definitions** -- each agent's purpose, inputs, outputs,
   tools, and autonomy boundaries
3. **Reasoning framework** -- how agents investigate, reason, and decide
   (with concrete examples for 2-3 alert scenarios)
4. **Knowledge architecture** -- case memory schema, retrieval strategy,
   feedback loop design
5. **Safety model** -- action classification matrix, approval workflows,
   blast radius controls
6. **Migration roadmap** -- phased plan from current to target architecture,
   ordered by impact and risk
7. **Key design decisions** -- explicit tradeoffs made and rationale for
   each major choice
