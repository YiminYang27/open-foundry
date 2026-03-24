---
agents:
  - role: system_architect
  - role: convention_explorer
  - role: example_explorer
  - role: critical_analyst
orchestrator: default
max_turns: 20
model: sonnet
---

# Should a Python project under 1000 lines adopt Dependency Injection?

Evaluate whether Dependency Injection (manual constructor injection or
framework-based DI containers) is justified in small Python projects
(< 1000 LOC, solo or small team). Python's dynamic nature, duck typing,
first-class functions, and module system provide alternatives to formal
DI that do not exist in static languages like Java or C#. The question
is where the cost-benefit tipping point lies.

## Architecture and Structural Impact

- At what module count and dependency depth does DI start providing real
  structural value vs adding wiring ceremony?
- How does DI affect the import graph in a < 1000 LOC Python project?
  Does it simplify or complicate module boundaries?
- What is the minimum project complexity (number of classes, external
  dependencies, configuration sources) where DI pays for itself?
- Manual constructor injection vs DI frameworks (dependency-injector,
  inject, punq) -- where is the framework overhead justified?

## Pythonic Conventions and Idiom Fit

- Does formal DI conflict with Python idioms (module-level singletons,
  duck typing, EAFP, simple imports)?
- How do experienced Python developers typically handle the problems DI
  solves (testing, configuration, loose coupling) without DI?
- What do Python style guides, PEPs, and community conventions say about
  DI patterns explicitly or implicitly?
- Is there a "Pythonic DI" that looks different from Java-style DI?

## Concrete Code Patterns

- Show a concrete < 1000 LOC Python example where DI clearly helps
  (before/after comparison with measurable benefit)
- Show a concrete example where DI adds complexity without benefit
- How does pytest's fixture system compare to constructor injection for
  test-time dependency replacement?
- Compare: direct instantiation vs constructor injection vs
  unittest.mock.patch vs pytest fixtures vs DI container -- for the
  same small codebase

## Critical Evaluation

- What are the hidden costs of DI in small projects (indirection,
  onboarding friction, over-abstraction, interface proliferation)?
- What are the hidden costs of NOT using DI (tight coupling, difficult
  testing, configuration sprawl)?
- Is "just use mock.patch" a valid long-term alternative to DI, or does
  it create its own technical debt?
- At what point does a project grow past the threshold where not having
  DI becomes painful? What are the warning signs?

## Deliverable

Produce a structured decision framework that includes:

1. **Decision criteria table**: concrete, measurable thresholds (LOC,
   dependency count, test coverage goals, team size) with a clear
   yes/no/maybe recommendation for DI at each level
2. **Pattern comparison**: side-by-side code examples showing the same
   small Python project implemented with and without DI, with analysis
   of tradeoffs
3. **Pythonic alternatives catalog**: Python-native patterns that solve
   DI's problems without a DI framework, with when each is appropriate
4. **Warning signs checklist**: indicators that a project has outgrown
   "no DI" and should consider adopting it
5. **Anti-patterns**: common DI mistakes in small Python projects
