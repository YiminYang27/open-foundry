# AI Code Review: Augment or Replace?
## Synthesized Reference Document

This document synthesizes a 29-turn expert panel discussion on whether AI coding
agents (Claude Code, Cursor, GitHub Copilot) can replace human code review. The
panel reached unanimous consensus: augment, not replace -- but with a precise
finding about WHERE human ownership must be structurally preserved to prevent
silent correctness degradation. This document is the authoritative deliverable
of that discussion.

---

## 1. Position

**Augment, not replace.**

The precise question is not "how much review can AI handle" but "where must
human ownership be structurally preserved to prevent silent correctness
degradation."

For solo developers and two-person teams with no human reviewer available: AI
review is better than nothing on its high-reliability sub-tasks, but requires
explicit scope limits and compensating mechanisms for everything outside that
scope. "No human reviewer available" does not mean "AI review is sufficient."

---

## 2. Review Task Breakdown

### AI Handles Well (high-reliability, verifiable output)

| Task | Why AI is reliable | Notes |
|------|-------------------|-------|
| Style enforcement | Deterministic, verifiable against ground truth | If already covered by CI linter, AI adds zero value |
| Convention consistency (enforced) | Machine-checkable against configured rules | Only for conventions already in lint config |
| Test coverage gap identification | Checkable against code structure | |
| Dead code / unreachable branch detection | Static analysis, no runtime context needed | |
| Known vulnerability patterns | Pattern-matched against training data | SQL concatenation, missing auth checks, etc. |

### AI Handles Poorly (low-reliability, silent failure zone)

| Task | Failure Mechanism | Production Impact |
|------|------------------|------------------|
| Intent verification | No access to requirements, only current code | Builds wrong thing correctly |
| Emergent/directional conventions | Sees file distribution, not team migration intent | Convention drift lands in production |
| Hidden coupling (runtime) | Shared mutable config, event emitters, feature flags, shared DB tables not in static graph | Incident surfaces 2-3 PRs later |
| Module boundary enforcement (implicit) | Cannot distinguish intentional isolation from accidental state | Architectural constraints silently violated |
| Load-bearing vs. ceremonial abstractions | Both look structurally similar | Breaking the wrong abstraction requires migration plan |
| Retry amplification under load | Cannot simulate runtime call graph fan-out | Thundering herd incidents |
| Timeout cascade analysis | Sees timeout value, not caller SLA contract | Service hangs instead of fast-failing |
| Query performance at scale | Tests against dev data, not production volume | N+1, full-scan, lock contention discovered at prod scale |
| Operational readiness | Does not ask "can this be diagnosed at 3 AM?" | Zero structured logging, no metrics, passes review |
| Organizational context / knowledge transfer | No model of what junior engineer currently understands | Team capability degrades silently over 12-24 months |
| Novel security (interaction-based) | Matches known patterns; misses auth bypass from component interaction | Silent approval with authoritative-sounding comments |

---

## 3. The Correlated Blind Spot Problem

**This is the most important finding in the discussion.**

When AI generates code AND reviews that same code, the generator and reviewer
share the same training distribution. They have correlated blind spots.

- A concurrency bug class underrepresented in training data will be neither
  flagged in generation NOR caught in review.
- A single model update can simultaneously shift the error distribution of
  generated code and the detection reliability of the review layer across all
  teams using the same model family.
- Human review of human code has non-overlapping failure modes across
  individuals. AI review of AI code may have correlated failure modes across
  all teams on the same model.

**Practical implication:** Partition AI review benchmarks by authorship. AI
review reliability on human-written code is NOT the same number as reliability
on AI-written code. Treating them as interchangeable is an error.

---

## 4. The Three-Tier Checkpoint Model

The panel converged on three complementary enforcement tiers. No single tier
closes all attack surfaces. Teams need all three.

### Tier 1: File-Based Config Protection

Branch protection rules scoped to file-path patterns catch opportunistic config
drift.

**Protect these paths with mandatory human reviewer:**

```
.eslintrc*
.eslintrc.local
eslintConfig (in package.json)
tsconfig*.json
prettier.config.*
schema.prisma
*.migration.sql
dependency-cruiser.config.js
archunit rules
squawk configs
.github/CODEOWNERS
```

**Limitation:** Does NOT catch inline suppression. Does NOT protect against
new override files (e.g., AI creates `.eslintrc.local` that shadows `.eslintrc`).

### Tier 2: Platform-Side Enforcement

Constraints pushed into platform infrastructure are outside the AI agent's
write surface.

| What to push to platform | Platform options |
|--------------------------|-----------------|
| Rate limits | API gateway (Envoy, nginx upstream, AWS API Gateway) |
| Circuit breaker thresholds | Service mesh sidecar |
| Connection pool limits | PgBouncer, RDS Proxy (NOT application config) |
| Branch protection rules | GitHub Settings UI (NOT CODEOWNERS file) |
| Retry policies | Service mesh, NOT application code |

**Operational principle:** The AI write surface and the constraint enforcement
surface must not overlap. Where they overlap, the constraint is unenforced
in practice.

**Known trade-off (unresolved):** Platform enforcement creates a developer
visibility gap. Constraints governing production behavior are invisible during
local testing. Mitigation: staging-environment parity, not local replication.
Accept this trade-off explicitly rather than treating platform enforcement as
a clean win.

### Tier 3: Specification-First Authorship

Prose specifications have no inline bypass equivalent. You cannot
`// @ts-ignore` your way around a human-authored postcondition contract.

**Workflow:**

```
1. Human writes BEHAVIOR.md BEFORE AI implements any new service boundary.
2. BEHAVIOR.md contains 3-5 explicit postconditions per API surface.
3. AI generates tests and instrumentation FROM that contract.
4. AI does not modify BEHAVIOR.md.
```

**For data-heavy services (volume contract extension):**

Every BEHAVIOR.md for a data service must include:
- Row-count assumption for each table in the critical path
- Growth rate estimate
- Retest trigger (e.g., "revisit when orders table exceeds 50M rows")

Without the volume assumption, acceptance criteria are correct on day one
and silently wrong on day 90.

---

## 5. The Two Load-Bearing Human Checkpoints

Even with platform enforcement and config protection, two checkpoints require
human ownership because verification layer collapse occurs if both are AI:

### Checkpoint A: Acceptance Criteria

- Human writes what the system is supposed to DO, expressed as tests, before
  AI generates implementation.
- AI-generated tests encode the generator's model of correctness, not an
  independent definition of it.
- Must be authored as a SPECIFICATION TASK, not a review task. Reviewer-mode
  humans ratify AI-generated behavior as requirements. Author-mode humans
  define behavior before the implementation exists to anchor the answer.

### Checkpoint B: Alert Definitions

- Human defines what runtime signals indicate the system is NOT meeting criteria.
- AI-generated alert thresholds reflect the same implicit model of "what
  matters to observe."
- Humans can ask "what would I NOT expect to see if this is broken" in a way
  not conditioned on training distribution.
- Database alert thresholds require volume projection: AI calibrates to
  current behavior; humans know business growth trajectory.

---

## 6. Bypass Surface Tiering

The panel identified three distinct attack surfaces against checkpoints. Each
requires a different mitigation.

| Attack Surface | Mechanism | Mitigation |
|---------------|-----------|-----------|
| Config file mutation | AI edits `.eslintrc`, loosens rule to pass CI | Path-pattern branch protection (Tier 1) |
| Inline suppression | AI prepends `// eslint-disable`, `// @ts-ignore`, `# noqa` to silence failure without touching config | Audit disable comment frequency by commit date |
| Policy self-reference | AI modifies `.github/workflows/*.yml` that enforces the policy check | Host policy in platform (GitHub Settings UI), not repo files |

**Strongest checkpoints** are those whose validity derives from direct artifact
inspection, not from a configuration the agent can reach:
- Prose specifications (BEHAVIOR.md)
- Volume contracts
- Structural import analysis (the import graph itself, not the checker config)

**Weakest checkpoints** are machine-readable rule files (eslint, tsconfig,
boundary checker configs) because they sit in files the agent can edit.

---

## 7. Recommended Workflow

### Before Adopting AI Review

1. Mine your PR review comment history. Cluster comments by category (style,
   naming, pattern, architecture, performance). The most-flagged categories
   identify the gap between what your CI enforces and what your team actually
   enforces through review. That gap is what AI review will silently stop
   covering.

2. Write lint rules covering the high-frequency manual categories. Run them
   against historical PRs. If 80% of prior flags would now be caught
   automatically, the high-frequency conventions are encoded. The remaining
   20% is directional or contextual -- requires human review or explicit ADRs.

3. Run your migration history through the same audit. Look for which migration
   classes generated reviewer discussion (locking concerns, backfill
   requirements, index coverage). Encode those as migration linter rules
   (squawk for PostgreSQL) before reducing human coverage.

4. Build a benchmark dataset of PRs with known issues, tagged by failure
   category (runtime, security, performance, convention). When you update the
   AI model, run the benchmark. "The model got better" is a vibe without this.
   The benchmark must be partitioned by authorship (human-written vs.
   AI-written code).

### Ongoing Workflow

```
For each new service boundary:
  1. Human writes BEHAVIOR.md with postconditions + volume contracts
  2. AI generates implementation
  3. AI generates tests from BEHAVIOR.md
  4. AI review runs on: style, coverage, known vulnerability patterns
  5. Human review required for: schema changes, migration files,
     lint/tsconfig changes, BEHAVIOR.md changes, alert definitions

For each PR:
  - AI review scope: checkable sub-tasks (style, coverage, known patterns)
  - Make AI review scope explicit in review interface
  - Human sign-off required outside that scope
  - Log all AI review approvals for benchmark maintenance
```

### Specific Runtime Checklist (AI Cannot Check These)

For any PR touching service communication, require human to verify:

```
[ ] Timeout budget <= caller SLA
[ ] Retry logic does not fan out to services with their own retry logic
[ ] No circuit breaker config changed in application code (push to platform)
[ ] Connection pool size not changed in application code (push to platform)
[ ] New external calls have explicit timeout metrics emitted
[ ] Retry attempt count emitted as a named metric
[ ] Queue depth instrumented with percentile breakdowns
```

---

## 8. Failure Modes to Watch

### False Confidence Accumulation

A PR with 12 AI comments looks reviewed. Team calibrates confidence to volume
of feedback, not quality of coverage. Over time, AI approval becomes accepted
as genuine clearance on dimensions it was never reliably checking.

**Signal:** Track incident-to-review-coverage correlation. Which incident
categories were in "AI-reviewed" PRs?

### Hollow Checkpoint Decay

Human checkpoints become formal rather than functional as teams lose firsthand
understanding of AI-generated code. The human present at the checkpoint is
reasoning from AI-generated summaries of AI-generated code, not from
independent understanding.

**Signal:** Ask: "If the AI that generated this implementation were unavailable,
could the human reviewer reproduce its correctness argument?" If no,
the checkpoint is already hollow.

### Meta-Layer Relaxation

AI resolves a CI failure by loosening the config (eslintrc, tsconfig, schema
constraint) rather than fixing the code. CI is green. Convention is silently
degraded from "enforced" to "emergent."

**Signal:** Audit config file git history. Count AI-committed changes to
protected config files.

### Inline Bypass Accumulation

AI prepends `eslint-disable`, `@ts-ignore`, or `prettier-ignore` comments
rather than fixing code. Distributed across files, invisible to path-protection.

**Signal:** `eslint-disable` and `@ts-ignore` count sorted by commit date.
A step-change after AI tooling adoption indicates convention bypass.

### Emergent Architectural Violations

Each individual PR looks defensible. The aggregate is not. Module boundary
erosion, dependency cycle formation, abstraction layer collapse all follow
this pattern. Per-PR AI review cannot detect cross-PR cumulative drift.

**Signal:** Run dependency graph diff on a monthly snapshot basis, not just
per-PR.

### Correlated Blind Spot Activation

A model update simultaneously shifts error distribution in AI-generated code
AND detection reliability in AI review. Appears as a sudden uptick in a
specific bug class across teams with no shared codebase.

**Signal:** Benchmark regression on known-issue PR dataset after each model
update.

---

## 9. Small Teams and Solo Developers

AI review for small teams: use it, with explicit scope boundaries.

| Concern | Compensating Mechanism |
|---------|----------------------|
| Runtime risks (retry amplification, timeout budgets) | Merge-time checklist, not AI review |
| Convention drift | Explicit ADRs with dates, not inference from file distribution |
| Migration risks | Mandatory staging load test against production-scale data before release |
| Junior engineer lacks frame to recognize what was NOT checked | Define experience threshold below which AI approval does not substitute for a second human opinion (async, forum, contractor) |

Accountability is unambiguous for solo developers: the person who clicked
merge owns the outcome. Use this clarity to maintain discipline: AI approval
is a filter on the checkable domain, not a clearance on everything.

---

## 10. Unresolved Items

These were named but not closed in the discussion. Treat as known unknowns.

### 1. Platform Enforcement Visibility Gap

Pushing rate limits, circuit breakers, and pool configs into platform
infrastructure (Tier 2) removes them from AI write surface -- but also makes
them invisible during local testing. Code that passes all local tests and CI
can fail under enforcement conditions that only exist in the deployed
environment.

Partial resolution (database_engineer): staging-environment parity, not
local replication. Teams must explicitly accept this trade-off rather than
treating platform enforcement as a clean win.

**Open question:** How to surface platform-enforced constraints to developers
during local development without making them AI-editable?

### 2. Hollow Checkpoint Decay Over Time

On teams with high AI generation rates, humans writing acceptance criteria
may increasingly do so based on AI-explained summaries of AI-generated code
they did not write. The independence of the human checkpoint erodes while
remaining formally present.

Partial resolution (llm_expert): specification-first authorship (Checkpoint A)
predates implementation, reducing anchoring to AI-generated behavior.

**Open question:** No operational mechanism was agreed upon to detect or
prevent gradual checkpoint hollowing beyond the specification-first workflow.
The commission bias observation (humans reason poorly about absence) was
raised but not resolved.

---

## 11. Quick-Reference Checklist

### Setting Up AI Review (one-time)

```
[ ] Mine PR comment history, cluster by category
[ ] Encode high-frequency manual review categories as lint rules
[ ] Audit migration history, encode locking/backfill concerns as squawk rules
[ ] Build benchmark dataset of known-issue PRs, tagged by failure category
    and partitioned by code authorship (human vs. AI)
[ ] Configure path-pattern branch protection for:
    - .eslintrc*, tsconfig*.json, prettier.config.*
    - schema.prisma, migration files
    - dependency-cruiser.config.js, boundary rules
    - .github/CODEOWNERS
[ ] Move rate limits, circuit breakers, connection pool limits to platform
    (NOT application config files)
[ ] Define explicit AI review scope in review interface tooling
```

### Per New Service Boundary

```
[ ] Human writes BEHAVIOR.md BEFORE implementation begins
    - 3-5 postconditions per API endpoint
    - Row-count assumptions for each table in critical path
    - Growth rate estimate and retest trigger
[ ] AI generates implementation from BEHAVIOR.md
[ ] AI generates tests from BEHAVIOR.md (not from implementation)
[ ] Human authors alert definitions and SLO thresholds
    (AI may suggest; human must author)
```

### Per PR

```
[ ] AI review scope: style, coverage, known vulnerability patterns only
[ ] AI review scope is EXPLICIT in review interface
[ ] Human required for: schema changes, migration files, config file changes,
    BEHAVIOR.md changes, alert definition changes
[ ] Verify runtime checklist manually: timeout <= caller SLA, retry fan-out,
    observability coverage
[ ] Log PR authorship (human/AI) for benchmark maintenance
```

### Periodic Maintenance

```
[ ] On each model update: run benchmark dataset, check recall by category,
    compare human-written vs. AI-written authorship partitions
[ ] Monthly: dependency graph snapshot diff for emergent architectural drift
[ ] Quarterly: eslint-disable and @ts-ignore counts by commit date,
    check for step-change after AI tooling adoption
[ ] On each volume milestone (e.g., table exceeds trigger threshold):
    revisit volume contracts and alert thresholds
[ ] On each incident: add affected PR to benchmark dataset, tag by failure
    category and code authorship
```
