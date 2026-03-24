# Structural Analysis: AI Code Review

## Core Position
Augment, with a structural caveat: AI handles intra-module review well,
fails at inter-module boundary enforcement.

## Where AI Review Fails Structurally

### 1. Implicit vs Enforced Boundaries
AI sees the current import graph. It does not know which boundaries were
*intentional architectural decisions* vs accidental current state.

Example: A module that currently has no cross-domain imports -- AI cannot
tell if that isolation is:
- A hard architectural rule (enforced by a build-time linter or ADR)
- Just how it happened to be written so far

A human reviewer who attended the architecture meeting knows the difference.
AI reviewing a PR that introduces the first cross-domain import from that
module will miss the violation unless the constraint is machine-readable.

### 2. Hidden Coupling Is Invisible to Static Analysis
AI excels at static analysis. Hidden coupling is NOT in the static graph:
- Shared mutable config objects passed at runtime
- Event emitters / pub-sub decoupling that creates implicit coupling
- Feature flags that create runtime conditional dependencies
- Database tables as implicit contracts between services

These are the exact things that pass AI review but cause production incidents.

### 3. Load-Bearing vs Ceremonial Abstractions
AI cannot distinguish between:
- An abstraction that exists because 12 modules depend on its interface contract
- An abstraction that exists because a developer liked the pattern

Both look structurally similar. A human who has worked in the codebase knows
which one you cannot touch without a migration plan.

## Where AI Review Is Structurally Superior
- Convention drift detection at scale (consistent, no fatigue)
- Dead code / unreachable branch identification
- Test coverage mapping
- Obvious security anti-patterns (SQL concatenation, missing auth checks)

## Key Failure Mode
Teams over-rely on AI review for *architectural* enforcement. AI approves
changes that look locally correct but violate implicit system-level contracts.
The incident happens 2-3 PRs later when the coupling surfaces.
