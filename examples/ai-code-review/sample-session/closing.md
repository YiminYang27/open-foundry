# Closing Summary

```
CLOSING SUMMARY: Should AI Coding Agents Replace Code Review?
=============================================================

POSITION
--------
Unanimous: augment, not replace. The discussion produced a more precise
finding -- the relevant question is not "how much review can AI handle"
but "where must human ownership be structurally preserved to prevent
silent correctness degradation."

KEY CONCLUSIONS AND AGREEMENTS
-------------------------------
The panel converged on a three-tier checkpoint model, built incrementally
across turns:

1. Two load-bearing human checkpoints (llm_expert, Turns 15/19):
   acceptance criteria and alert definitions. AI review of AI-generated
   code has distributional dependence -- shared blind spots -- making
   these two points the minimum human ownership required.

2. Object-layer vs. meta-layer permission boundary (system_architect,
   Turn 23): AI agents with write access to config files (.eslintrc,
   schema.prisma, boundary-checker configs) can redefine correctness
   from underneath any checkpoint built on top of them. File-path-based
   branch protection is the first-order mitigation.

3. Platform-side enforcement over in-repo policy (critical_analyst, Turn 24;
   backend_engineer, Turn 25): repo-file enforcement can be reached and
   modified by the AI agent. Rate limits, circuit breakers, and pool configs
   pushed into platform infrastructure (Envoy, PgBouncer, API gateway)
   are outside the agent write surface. Enforcement that lives in a file
   the agent can edit is unenforced in practice.

4. Specification-first authorship (llm_expert, Turn 26; convention_explorer,
   Turn 28): a human-authored BEHAVIOR.md predating AI implementation
   provides the only checkpoint with no inline bypass path. You cannot
   // eslint-disable around a prose postcondition contract.

5. Bypass surface tiering (system_architect, Turn 29): three distinct
   attack surfaces against checkpoints require different mitigations --
   config mutation (path-pattern protection), inline suppression
   (eslint-disable, @ts-ignore), and policy self-reference (CI workflow
   files the agent can modify). No single file-protection strategy closes
   all three.

UNRESOLVED DISAGREEMENTS
------------------------
One genuine trade-off was named but not resolved: pushing enforcement
into platform infrastructure (the backend_engineer's recommendation)
creates a developer visibility gap -- constraints that govern production
behavior are invisible during local testing. The llm_expert flagged this
explicitly. The database_engineer's resolution (staging-environment parity,
not local replication) is partial; teams need to accept this trade-off
explicitly rather than treat platform enforcement as a clean win.

The hollow-checkpoint decay problem (critical_analyst, Turn 20) --
where human checkpoints become formal rather than functional as teams
lose firsthand understanding of AI-generated code -- was identified but
not operationally resolved beyond the specification-first workflow.

CONCRETE RECOMMENDATIONS
------------------------
For teams evaluating AI-assisted code review:

1. Partition AI review benchmarks by authorship (human-written vs.
   AI-written code). Reliability numbers are not interchangeable.
   Establish this before extending AI review scope.

2. Require a human-authored BEHAVIOR.md or service contract before AI
   implementation begins on any new service boundary. Three to five
   explicit postconditions per API surface is sufficient.

3. Include volume contracts in all data-service specifications: row-count
   assumptions, growth rate estimates, and retest triggers. Performance
   acceptance criteria without volume context are formally hollow.

4. Treat schema/migration files and lint/tsconfig configs as protected
   checkpoints with mandatory human review. AI agents flag; they do not
   commit. The blast radius for a dropped column differs from a relaxed
   lint rule.

5. Audit eslint-disable and @ts-ignore frequency by commit date. A
   step-change after AI tooling adoption indicates the convention layer
   is being bypassed inline, which path-protection does not catch.

6. On teams with high AI generation rates, increase investment in runtime
   instrumentation over review-layer detection. Explicit timeout metrics
   at every external call boundary, retry attempt counts as named metrics,
   queue depth with percentile breakdowns. This compensates for correlated
   review blind spots.

7. Tier your checkpoints by bypass surface before treating any as
   load-bearing: file-based config protection, platform-side enforcement,
   and specification-first authorship each close a different attack surface.

MOST VALUABLE INSIGHTS
----------------------
The critical_analyst's correlated failure mode (Turn 17) reframed the
entire discussion: the concern is not that AI review is worse than human
review in isolation, but that AI generator and AI reviewer share the same
training distribution, creating correlated blind spots invisible to any
per-PR benchmark. A single model update could simultaneously shift the
error distribution of generated code and the detection reliability of the
review layer across all teams using the same model family.

The convention_explorer's inline suppression observation (Turn 28) provided
the cleanest structural insight: prose specifications have no // @ts-ignore
equivalent. This is an underappreciated architectural property that makes
specification-first authorship structurally stronger than machine-readable
rule enforcement, not just procedurally preferable.

The database_engineer's volume contract extension (Turn 27) is the most
actionable amendment to the llm_expert's proposal: acceptance criteria
for data-heavy services must include row-count assumptions and growth
rate estimates, or they are correct on day one and silent failures on
day 90. This applies to human and AI review equally.
```

## Statistics

- Total turns: 29
- Speaker breakdown:
- [operator]: 1 turns
- backend_engineer: 4 turns
- convention_explorer: 4 turns
- critical_analyst: 6 turns
- database_engineer: 4 turns
- llm_expert: 5 turns
- system_architect: 5 turns
- Consensus: yes
- Model: sonnet
- Completed: 2026-03-24 20:54
