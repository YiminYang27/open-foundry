# SOLID Refactor: Architecture & Code Flow

Date: 2026-03-28

## 1. Overview

Decomposed the original 1519-line `forge.py` monolith into a class-based
package following SOLID principles. The `forge/` package now has clear
separation of concerns, dependency injection, and no module-level mutable state.

### Package Structure

```
forge/
  __init__.py              Package entry, exports main()
  app.py              96   Composition root: dependency wiring + pipeline launch
  workflow.py        332   ForumWorkflow: discussion loop + phase transitions
  orchestrator.py    277   OrchestratorService: pick, verify, finalize, execution
  agents.py          118   AgentService: speak, execute, parse_status_signal
  synthesis.py       133   SynthesisService: synthesize, review
  session_io.py      349   SessionManager: session lifecycle + all file I/O
  models/
    models.py         57   Agent, Orchestrator, Session, ForumContext
  llm/
    llm.py           136   LLMProvider Protocol + ClaudeCLI implementation
  roles/
    roles.py         129   RoleStore + parse_mission
  utils/
    cli.py           103   parse_args(), resolve_paths()
    logger.py         67   Logger class (singleton)
    parsers.py        42   extract_json(), parse_frontmatter()
  prompts/
    __init__.py       19   load_template()
    *.md                   8 prompt templates
```

### Class Dependency Graph

```
app.py (composition root)
  |
  |-- constructs --> ClaudeCLI, RoleStore, SessionManager, ForumContext
  |-- constructs --> AgentService(llm, smgr)
  |-- constructs --> OrchestratorService(llm, smgr)
  |-- constructs --> SynthesisService(llm, smgr, role_store)
  |-- constructs --> ForumWorkflow(smgr, ctx, orch_svc, agent_svc, synth_svc)
  +-- calls      --> workflow.run()

ForumWorkflow ---delegates--> OrchestratorService, AgentService,
                              SynthesisService, SessionManager

OrchestratorService ---uses--> SessionManager, ClaudeCLI, load_template, extract_json
AgentService        ---uses--> SessionManager, ClaudeCLI, load_template
SynthesisService    ---uses--> SessionManager, ClaudeCLI, RoleStore,
                               load_template, extract_json
SessionManager      ---uses--> Session (dataclass), Logger
```

---

## 2. Code Flow

### Step 1: Bootstrap (app.py::main)

```
main()
  |-- utils/cli.parse_args()              # argparse -> Namespace
  |-- utils/cli.resolve_paths(args)       # -> (project_root, mission_path, resume_dir)
  |
  |-- roles.parse_mission(mission_path)   # parse MISSION.md frontmatter + body
  |                                       # -> (agent_names, max_turns, model, orch_name,
  |                                       #     title, mission_body, execute_after)
  |
  |-- ClaudeCLI(model, dry_run)           # construct LLM provider
  |-- RoleStore(project_root / "roles")   # construct role loader
  |     |-- .get_agent(name) x N          # load each agent .md -> Agent
  |     +-- .get_orchestrator(orch_name)  # load orchestrator .md -> Orchestrator
  |
  |-- ForumContext(agents, orch, ...)      # aggregate shared params
  |
  |-- [new]    SessionManager.create(project_root, slug, mission_path, ...)
  |              -> creates work_dir, transcript.md, notes/, utterances/
  |-- [resume] SessionManager.resume(work_dir, agents)
  |              -> loads state.json, rebuilds speakers_history
  |
  |-- AgentService(llm, smgr)
  |-- OrchestratorService(llm, smgr)
  |-- SynthesisService(llm, smgr, role_store)
  |
  |-- ForumWorkflow(smgr, ctx, orch_svc, agent_svc, synth_svc)
  +-- workflow.run(execute_after, feedback, synthesize_only, ...)
```

### Step 2: Pipeline Entry (ForumWorkflow.run)

```
workflow.run(...)
  |
  |-- [if resume + completed + feedback]
  |     smgr.archive_outputs()            # rename closing.md, synthesis.md
  |
  |-- register signal handlers (SIGINT -> graceful exit, SIGQUIT -> pause)
  |-- print banner (topic, agents, model, output dir)
  |
  |-- [if feedback]
  |     smgr.inject_operator_turn(feedback)
  |     smgr.update_state("running")
  |
  |-- [if synthesize_only] -----> Step 5 (shortcut)
  |
  +-- _run_discussion_loop()  -----> Step 3
```

### Step 3: Discussion Loop (ForumWorkflow._run_discussion_loop)

Each turn repeats this cycle:

```
while session.utterances < ctx.max_turns:
  |
  |-- orch_svc.pick_speaker(ctx)
  |     |-- smgr.get_transcript_context(recent_turns)
  |     |-- load_template("orchestrator_pick", stats, signals, transcript...)
  |     |-- llm.complete(prompt)
  |     +-- extract_json(raw) -> {"speaker", "action", "reasoning"}
  |
  |-- smgr.append_orchestrator_turn(pick_result)
  |
  |-- [CONSENSUS] -----> Step 4
  |-- [FALLBACK]  OrchestratorService.next_round_robin(agents, last)
  |-- [3x repeat] OrchestratorService.next_round_robin(agents, speaker)
  |
  |-- [speak]
  |     agent_svc.speak(agent, ctx)
  |       |-- smgr.get_transcript_context(recent_turns)
  |       |-- load_template("agent_speak", persona, mission, transcript...)
  |       +-- llm.complete(prompt)
  |
  |-- [execute]
  |     agent_svc.execute(agent, ctx, task)
  |       |-- smgr.get_transcript_context(recent_turns)
  |       |-- load_template("agent_execute", persona, task, handoff...)
  |       +-- llm.complete(prompt)
  |
  |-- smgr.append_agent_turn(speaker, response, action, task)
  |-- session.utterances += 1
  |
  |-- [speak] AgentService.parse_status_signal(response)
  |             -> session.agent_statuses[speaker] = signal
  |
  |-- [execute + verify_persona] VERIFY LOOP (max 3):
  |     |-- orch_svc.verify_task(ctx, task, response)
  |     |     |-- load_template("verify_task", persona, task, response...)
  |     |     +-- llm.complete(prompt) -> extract_json -> {"status", "details"}
  |     |-- smgr.append_verification(turn_label, status, details)
  |     |-- [pass] break
  |     +-- [fail + retries left]
  |           agent_svc.execute(agent, ctx, retry_task)
  |           smgr.append_retry_turn(speaker, response, retry_num, task)
  |
  |-- smgr.update_state("running")
  |
  |-- [pause check]
  |     _check_pause() -> SIGQUIT flag or PAUSE file
  |     smgr.inject_operator_turn(msg)
  |
  +-- next turn
```

### Step 4: Post-Discussion (ForumWorkflow._finalize_and_synthesize)

Triggered by consensus OR max turns:

```
_finalize_and_synthesize(consensus_status, ...)
  |
  |-- smgr.update_state("completed")
  |
  |-- orch_svc.finalize(ctx, consensus_status)
  |     |-- smgr.truncate_transcript_for_closing()
  |     |-- load_template("finalize", persona, truncated_transcript)
  |     |-- llm.complete(prompt) -> closing summary text
  |     +-- write closing.md (summary + speaker breakdown + stats)
  |
  |-- [if execute_after]
  |     orch_svc.run_execution_phase(ctx, agent_svc)
  |       |-- load_template("task_decompose", persona, closing, agents)
  |       |-- llm.complete(prompt) -> extract_json -> {"tasks": [...]}
  |       +-- for each task:
  |             agent_svc.execute(agent, ctx, task_def)
  |             orch_svc.verify_task(ctx, task_def, response)
  |             [retry loop up to 3x]
  |
  |-- synth_svc.synthesize(mission_body)
  |     |-- role_store.get_synthesizer_persona()
  |     |-- load_template("synthesize", persona, notes, transcript, closing...)
  |     +-- llm.stream(prompt)  # streaming, writes synthesis.md directly
  |
  +-- synth_svc.review()
        |-- load_template("synthesis_review", transcript, closing, synthesis)
        |-- llm.complete(prompt) -> extract_json -> {"status", "issues"}
        +-- write review.json
```

### Step 5: Synthesize-Only (shortcut)

```
[synthesize_only = True]
  |-- [if no closing.md] orch_svc.finalize(ctx, "unknown")
  |-- synth_svc.synthesize(mission_body)
  +-- synth_svc.review()
```

---

## 3. Module Responsibilities

| Module | Class | Methods | Single Responsibility |
|--------|-------|---------|----------------------|
| app.py | - | main() | Parse CLI, wire deps, launch pipeline |
| workflow.py | ForumWorkflow | run, _run_discussion_loop, _finalize_and_synthesize, _check_pause | Loop control + phase transitions |
| orchestrator.py | OrchestratorService | pick_speaker, verify_task, finalize, run_execution_phase, next_round_robin | All orchestrator-driven LLM calls |
| agents.py | AgentService | speak, execute, parse_status_signal | All agent-driven LLM calls |
| synthesis.py | SynthesisService | synthesize, review | Post-discussion synthesis + quality check |
| session_io.py | SessionManager | create, resume, update_state, append_*, archive_outputs, inject_operator_turn, get_transcript_context, truncate_transcript_for_closing | All session filesystem I/O |
| models/ | Agent, Orchestrator, Session, ForumContext | (dataclasses) | Pure data structures |
| llm/ | ClaudeCLI, LLMProvider | complete, stream | LLM provider abstraction |
| roles/ | RoleStore | get_agent, get_orchestrator, get_synthesizer_persona | Role file loading |
| utils/cli.py | - | parse_args, resolve_paths | CLI argument parsing |
| utils/logger.py | Logger | info, ok, warn, err, fatal, speaker_line | Logging |
| utils/parsers.py | - | extract_json, parse_frontmatter | Generic parsing |
| prompts/ | - | load_template | Template loading |

---

## 4. Session Directory Layout

Each run produces:

```
sessions/{slug}-{timestamp}/
  MISSION.md              Copy of source mission
  transcript.md           Full discussion with turns
  closing.md              Closing summary + statistics
  synthesis.md            Final deliverable document
  review.json             Synthesis quality review result
  state.json              Session state (utterances, speakers, status)
  orchestrator.log        JSON-per-line orchestrator decisions
  runtime.log             Timestamped log of all info/warn/ok output
  utterances/             Individual turn files ({timestamp}-{speaker}.md)
  notes/
    {agent_name}/         Per-agent working notes
    _operator/            Operator intervention records
    _verification/        Task verification results
```

---

## 5. Design Principles Applied

**S - Single Responsibility**: Each module has exactly one reason to change.
Workflow changes? Edit workflow.py. Prompt format changes? Edit prompts/.
Session format changes? Edit session_io.py.

**O - Open/Closed**: New LLM providers implement LLMProvider Protocol without
modifying existing code. New orchestration strategies can subclass
OrchestratorService.

**L - Liskov Substitution**: LLMProvider is a Protocol (structural subtyping).
Any class with a matching complete() method satisfies it.

**I - Interface Segregation**: LLMProvider requires only complete(). The
stream() method is ClaudeCLI-specific, checked via hasattr().

**D - Dependency Inversion**: High-level modules (ForumWorkflow) depend on
abstractions (LLMProvider, SessionManager), not concretions. All dependencies
are injected via constructors in app.py.

---

## 6. Next: LLM Provider Redesign

### Problem

Current `forge/llm/llm.py` mixes interface and implementation in one file.
`LLMProvider` is a Protocol with only `complete()` -- `stream()` is
ClaudeCLI-specific, checked via `hasattr()` in callers. All service type
hints use `ClaudeCLI` concretely, violating Dependency Inversion.

### Target Structure

```
forge/llm/
  __init__.py              Re-exports: LLMProvider, LLMProviderFactory, ClaudeCLI
  llm_provider.py          Abstract base class (ABC) with complete() + stream()
  llm_provider_factory.py  Factory: create provider by name
  claude_cli.py            ClaudeCLI(LLMProvider) -- concrete implementation
  # future:
  # codex_cli.py           CodexCLI(LLMProvider)
  # gemini_cli.py          GeminiCLI(LLMProvider)
  # anthropic_api.py       AnthropicAPI(LLMProvider) -- direct API
```

### LLMProvider ABC

```python
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    """Base class for all LLM providers.

    Subclasses must implement complete() and stream().
    If a provider does not support streaming, stream() returns None.
    """

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def dry_run(self) -> bool: ...

    @abstractmethod
    def complete(self, prompt: str, *,
                 label: str = "",
                 timeout: int = 600,
                 max_retries: int = 3) -> str:
        """Send prompt, return response text. Empty string on failure."""
        ...

    @abstractmethod
    def stream(self, prompt: str, *,
               label: str = "",
               timeout: int = 1800,
               max_retries: int = 3) -> int | None:
        """Send prompt with streaming output.
        Return exit code (0 = success), or None if unsupported.
        """
        ...
```

Key change: `stream()` is now part of the contract. Providers that don't
support it return `None`. Callers check `rc is not None` instead of
`hasattr(llm, 'stream')`.

### LLMProviderFactory

```python
class LLMProviderFactory:
    """Create LLM provider instances by name."""

    @staticmethod
    def create(provider: str = "claude-cli", *,
               model: str = "sonnet",
               dry_run: bool = False,
               **kwargs) -> LLMProvider:
        if provider == "claude-cli":
            return ClaudeCLI(model=model, dry_run=dry_run, **kwargs)
        raise ValueError(f"Unknown LLM provider: {provider}")
```

### ClaudeCLI

Moved to `claude_cli.py`, inherits `LLMProvider`:

```python
class ClaudeCLI(LLMProvider):
    def complete(...) -> str: ...    # existing logic
    def stream(...) -> int | None: ... # returns int (exit code), never None
```

### Caller Changes

All type hints change from `ClaudeCLI` to `LLMProvider`:
- `OrchestratorService.__init__(self, llm: LLMProvider, ...)`
- `AgentService.__init__(self, llm: LLMProvider, ...)`
- `SynthesisService.__init__(self, llm: LLMProvider, ...)`
- `ForumWorkflow.__init__(self, ..., llm: LLMProvider, ...)`

`synthesis.py` changes from `hasattr` check to return value check:
```python
# before:
if hasattr(self._llm, 'stream'):
    rc = self._llm.stream(...)

# after:
rc = self._llm.stream(...)
if rc is not None:
    ...
```

`app.py` changes from direct construction to factory:
```python
# before:
llm = ClaudeCLI(model=model, dry_run=args.dry_run)

# after:
llm = LLMProviderFactory.create("claude-cli", model=model, dry_run=args.dry_run)
```

### DI Flow After Change

```
app.py
  |-- LLMProviderFactory.create("claude-cli", model, dry_run)
  |     -> returns LLMProvider (actually ClaudeCLI)
  |
  |-- AgentService(llm: LLMProvider, smgr)
  |-- OrchestratorService(llm: LLMProvider, smgr)
  |-- SynthesisService(llm: LLMProvider, smgr, role_store)
  |-- ForumWorkflow(smgr, ctx, llm, orch_svc, agent_svc, synth_svc)
  +-- workflow.run(...)
```

No module outside `forge/llm/` and `forge/app.py` ever references `ClaudeCLI`
directly. All business logic depends on the `LLMProvider` abstraction.
