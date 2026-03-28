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
  workflow.py        332   MissionWorkflow: discussion loop + phase transitions
  orchestrator.py    277   OrchestratorService: pick, verify, finalize, execution
  agents.py          118   AgentService: speak, execute, parse_status_signal
  synthesis.py       133   SynthesisService: synthesize, review
  session_io.py      349   SessionManager: session lifecycle + all file I/O
  models/
    models.py         57   Agent, Orchestrator, Session, MissionContext
  llm/
    llm_provider.py   41   LLMProvider ABC (complete + stream contract)
    claude_cli.py     99   ClaudeCLI(LLMProvider) concrete implementation
    llm_provider_factory.py 17  Factory: create provider by name
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
  |-- LLMProviderFactory.create("claude-cli", model, dry_run)
  |     -> returns LLMProvider (abstraction)
  |-- constructs --> RoleStore, SessionManager, MissionContext
  |-- constructs --> AgentService(llm: LLMProvider, smgr)
  |-- constructs --> OrchestratorService(llm: LLMProvider, smgr)
  |-- constructs --> SynthesisService(llm: LLMProvider, smgr, role_store)
  |-- constructs --> MissionWorkflow(smgr, ctx, llm, orch_svc, agent_svc, synth_svc)
  +-- calls      --> workflow.execute()

MissionWorkflow ---delegates--> OrchestratorService, AgentService,
                              SynthesisService, SessionManager

OrchestratorService ---uses--> SessionManager, LLMProvider, load_template, extract_json
AgentService        ---uses--> SessionManager, LLMProvider, load_template
SynthesisService    ---uses--> SessionManager, LLMProvider, RoleStore,
                               load_template, extract_json
SessionManager      ---uses--> Session (dataclass), Logger
```

---

## 2. Code Flow -- Step-by-Step Walkthrough

Tracing `./scripts/forge.py ai-code-review --model haiku --max-turns 5`
through every file and function call.

### Step 1: Entry

```
scripts/forge.py:6    sys.path.insert(0, project_root)
scripts/forge.py:7    from forge import main
scripts/forge.py:9    main()
```

`forge/__init__.py:3` re-exports `main` from `forge.app`.

### Step 2: CLI Parsing (app.py:17 -> utils/cli.py)

```
app.py:18     args = parse_args()
```

`utils/cli.py:35 parse_args()` -- builds argparse parser, returns Namespace
with: `args.mission="ai-code-review"`, `args.model="haiku"`,
`args.max_turns=5`, `args.dry_run=False`, `args.resume=None`,
`args.feedback=None`, `args.synthesize_only=False`.

```
app.py:25     project_root, mission_path, resume_dir = resolve_paths(args)
```

`utils/cli.py:62 resolve_paths()`:
- Walks up from `forge/utils/` to find `CLAUDE.md` -> `project_root`
- Tries `missions/ai-code-review` -> finds directory
- Appends `MISSION.md` -> `mission_path = missions/ai-code-review/MISSION.md`
- `resume_dir = None`

### Step 3: Mission Parsing (app.py:32 -> roles/roles.py)

```
app.py:33     (agent_names, max_turns, model, orch_name, title,
               mission_body, execute_after) = parse_mission(mission_path)
```

`roles/roles.py:30 parse_mission()`:
- Calls `utils/parsers.py:30 parse_frontmatter()` -- regex extracts YAML
  frontmatter (`---\n...\n---`) and body
- Parses frontmatter lines: `- role: system_architect`, `max_turns: 30`, etc.
- Extracts title from first `# ` heading in body
- Returns 7 values; CLI overrides applied at app.py:39-42

### Step 4: Dependency Construction (app.py:47-88)

```
app.py:48     role_store = RoleStore(project_root / "roles")
app.py:49     llm = LLMProviderFactory.create("claude-cli", model="haiku", dry_run=False)
```

`llm/llm_provider_factory.py:14 create()`:
- Matches `"claude-cli"` -> imports `ClaudeCLI` from `llm/claude_cli.py`
- Returns `ClaudeCLI(model="haiku", skip_perms=True, dry_run=False)`
- Return type is `LLMProvider` (the ABC)

```
app.py:52     agents = [role_store.get_agent(name) for name in agent_names]
```

`roles/roles.py:79 RoleStore.get_agent("system_architect")`:
- Searches `roles/` recursively for `system_architect.md`
- Calls `parse_frontmatter()` -> extracts `expertise:` from frontmatter
- Returns `Agent(name="system_architect", expertise="...", persona="...")`
- Repeated for each agent in the mission roster

```
app.py:55     orch = role_store.get_orchestrator("default")
```

`roles/roles.py:99 RoleStore.get_orchestrator("default")`:
- Reads `roles/orchestrator/default.md`
- Splits body by `## ` headers -> extracts Speaker Selection, Closing
  Summary, Verification sections
- Returns `Orchestrator(name, pick_persona, close_persona, verify_persona)`

```
app.py:58     ctx = MissionContext(agents, orch, agent_list_str, max_turns=5,
                                 mission_body, mission_dir, recent_window=10)
```

`models/models.py:48 MissionContext` -- immutable dataclass aggregating all
shared discussion parameters.

### Step 5: Session Setup (app.py:68-78)

```
app.py:75     smgr = SessionManager.create(project_root, "ai-code-review",
                                            mission_path, agents, title, 5, "haiku", mission_body)
```

`session_io.py:30 SessionManager.create()`:
- Creates `sessions/ai-code-review-20260328-HHMMSS/`
- Writes `MISSION.md` (copy with source comment)
- Creates `transcript.md` with header (title, agents, model, date)
- Creates `utterances/`, `notes/{agent}/`, `notes/_operator/`
- Touches `orchestrator.log`
- Returns `SessionManager(session)` wrapping the `Session` dataclass

```
app.py:77     smgr.update_state("starting", agents, 5, "haiku", str(mission_path))
```

`session_io.py:137 SessionManager.update_state()`:
- Writes `state.json` with utterances=0, status="starting", agents list

### Step 6: Service Wiring (app.py:82-88)

```
app.py:83     agent_svc  = AgentService(llm, smgr)
app.py:84     orch_svc   = OrchestratorService(llm, smgr)
app.py:85     synth_svc  = SynthesisService(llm, smgr, role_store)
app.py:88     workflow    = MissionWorkflow(smgr, ctx, llm, orch_svc, agent_svc, synth_svc)
```

Each service stores references to `llm: LLMProvider` and `smgr: SessionManager`.
No service knows about concrete `ClaudeCLI` -- all typed against `LLMProvider`.

### Step 7: Pipeline Start (app.py:89 -> workflow.py:41)

```
app.py:89     workflow.execute(execute_after=False, feedback=None,
                           synthesize_only=False, mission_path=..., ...)
```

`workflow.py:41 MissionWorkflow.execute()`:
- Lines 61-74: Check if resuming completed session (not applicable here)
- Lines 84-89: Register signal handlers (SIGINT -> graceful exit,
  SIGQUIT -> pause)
- Lines 91-104: Print banner (title, agents, max turns, model, output dir)
- Lines 107-109: Feedback injection (skipped, feedback=None)
- Lines 112-135: Synthesize-only mode (skipped)
- Line 140: `self._run_discussion_loop(...)`

### Step 8: Discussion Loop -- Turn 1 (workflow.py:148)

```
workflow.py:154   while session.utterances < 5:     # utterances=0, enters loop
workflow.py:158       pick_result = self._orch_svc.pick_speaker(ctx)
```

`orchestrator.py:32 OrchestratorService.pick_speaker(ctx)`:
- Line 35: `smgr.get_transcript_context(recent_turns=10)` -- reads
  transcript.md, returns full content (< 10 turns)
- Lines 39-43: Build speaker stats from `session.speakers_history`
  (empty on turn 1)
- Lines 46-63: Build recent decisions from `orchestrator.log`
  (empty on turn 1)
- Lines 66-74: Build action block (if orchestrator has verify_persona)
- Lines 77-91: Build agent status signals (empty on turn 1)
- Lines 93-102: `load_template("orchestrator_pick", ...)` -- loads
  `prompts/orchestrator_pick.md`, substitutes all `{variables}`
- Line 104: `llm.complete(prompt, label="Orchestrator", timeout=120)`

`llm/claude_cli.py:30 ClaudeCLI.complete()`:
- Builds cmd: `['claude', '-p', '-', '--model', 'haiku',
  '--dangerously-skip-permissions']`
- `subprocess.run(cmd, input=prompt, capture_output=True, text=True,
  timeout=120, start_new_session=True)`
- Returns `result.stdout.strip()`

Back in `pick_speaker`:
- Line 111: `extract_json(raw)` (`utils/parsers.py:8`) -- parses JSON from
  LLM response, handles markdown fences
- Lines 114-115: Appends JSON to `orchestrator.log`
- Returns e.g. `{"speaker": "critical_analyst", "action": "speak",
  "reasoning": "..."}`

```
workflow.py:159   self._smgr.append_orchestrator_turn(pick_result)
```

`session_io.py:195 SessionManager.append_orchestrator_turn()`:
- Writes `utterances/HHMMSS-host.md` with speaker, action, reasoning

```
workflow.py:161   speaker = "critical_analyst"
workflow.py:163   action = "speak"
```

Lines 166-182: Not CONSENSUS, skip.
Lines 185-192: Not FALLBACK, skip.
Lines 195-203: Anti-loop guard check (consecutive_count=1, ok).

```
workflow.py:215   response = self._agent_svc.speak(agent, ctx)
```

`agents.py:36 AgentService.speak(agent, ctx)`:
- Line 39: `smgr.get_transcript_context(recent_turns=10)`
- Lines 42-50: Build refs_block (check for `references/` dir in mission)
- Lines 52-60: `load_template("agent_speak", ...)` -- substitutes agent
  persona, mission body, transcript, notes_dir, turn/max info
- Line 62: `llm.complete(prompt, label="Agent critical_analyst")`
  -> Claude CLI subprocess -> returns agent response text

```
workflow.py:220   self._smgr.append_agent_turn("critical_analyst", response, "speak")
```

`session_io.py:172 SessionManager.append_agent_turn()`:
- Writes `utterances/HHMMSS-critical_analyst.md`
- Appends to `transcript.md`:
  `### Turn 1 -- critical_analyst [HH:MM]\n{response}\n\n---\n\n`

```
workflow.py:222   session.utterances += 1       # now 1
workflow.py:223   session.last_speaker = "critical_analyst"
workflow.py:224   session.speakers_history.append("critical_analyst")
workflow.py:228   session.agent_statuses["critical_analyst"] = AgentService.parse_status_signal(response)
```

`agents.py:19 AgentService.parse_status_signal()` (static):
- Scans last lines of response for `[ANALYSIS_COMPLETE]`,
  `[NEEDS_DATA:...]`, etc.
- Returns e.g. `{"signal": "NONE"}`

```
workflow.py:269   _save_state("running")
```

`session_io.py:137 SessionManager.update_state()`:
- Writes `state.json` with utterances=1, status="running"

```
workflow.py:275   # pause check (skipped, no SIGQUIT, no PAUSE file)
```

**Turn 1 complete.** Loop repeats for turns 2-5.

### Step 9: Consensus or Max Turns

**If orchestrator returns `speaker="CONSENSUS"`** (workflow.py:166):

```
workflow.py:167   logger.ok("Consensus reached: ...")
workflow.py:168   self._finalize_and_synthesize(consensus_status="yes", ...)
```

-> Jump to Step 10.

**If max turns reached** (workflow.py:293, loop exits naturally):

```
workflow.py:294   logger.warn("Max turns (5) reached without consensus")
workflow.py:295   self._finalize_and_synthesize(consensus_status="no (max turns reached)", ...)
```

-> Jump to Step 10.

### Step 10: Finalize (workflow.py:311 -> orchestrator.py:144)

```
workflow.py:316   _save_state("completed")
workflow.py:317   self._orch_svc.finalize(ctx, "yes")
```

`orchestrator.py:144 OrchestratorService.finalize(ctx, "yes")`:
- Line 147: Read full transcript, count speakers from `### Turn` headers
- Line 160: `smgr.truncate_transcript_for_closing(keep_recent=15)`
  (`session_io.py:267`) -- keeps header + each agent's last turn + recent
  15 turns
- Line 162: `load_template("finalize", close_persona, truncated)`
- Line 166: `llm.complete(prompt)` -> Claude generates closing summary
- Lines 171-182: Write `closing.md` with summary + statistics (total turns,
  speaker breakdown, consensus status, model, timestamp)

### Step 11: Execution Phase (optional, workflow.py:318)

Only if `execute_after=True` in MISSION.md:

```
workflow.py:319   self._orch_svc.run_execution_phase(ctx, self._agent_svc)
```

`orchestrator.py:186 OrchestratorService.run_execution_phase(ctx, agent_svc)`:
- Line 201: Read `closing.md`
- Line 202: `load_template("task_decompose", ...)` -- asks LLM to decompose
  conclusions into executable tasks
- Line 207: `llm.complete(prompt)` -> `extract_json()` ->
  `{"tasks": [{"agent": "...", "task": "...", "verify": "..."}, ...]}`
- Lines 225-275: For each task:
  - `agent_svc.execute(agent, ctx, task_def)` -- agent implements
  - `self.verify_task(ctx, task_def, response)` -- orchestrator verifies
  - If fail: append failure to task, retry (up to 3x)

### Step 12: Synthesize (workflow.py:320 -> synthesis.py:22)

```
workflow.py:320   self._synth_svc.synthesize(ctx.mission_body)
```

`synthesis.py:22 SynthesisService.synthesize(mission_body)`:
- Line 27: `role_store.get_synthesizer_persona()` -> loads
  `roles/general/synthesizer.md`
- Lines 35-40: Build notes inventory (list files in `notes/` with sizes)
- Lines 43-51: Check for archived synthesis (from `--feedback` runs)
- Lines 53-61: `load_template("synthesize", persona, notes, transcript,
  closing, prev_synthesis, synthesis_file)`
- Line 69: `llm.stream(prompt, timeout=1800, max_retries=1)`

`llm/claude_cli.py:69 ClaudeCLI.stream()`:
- `subprocess.run(['claude', '-p', '-', '--model', 'haiku',
  '--dangerously-skip-permissions'], input=prompt, capture_output=False,
  text=True, timeout=1800, start_new_session=True)`
- `capture_output=False` lets user see live progress
- Synthesizer uses Claude's file tools to write `synthesis.md` directly
- Returns exit code (0 = success)

Back in `synthesize()`:
- Lines 71-84: If stream failed, retry up to 3x with partial backup
- Lines 91-95: Log line count of produced synthesis

### Step 13: Review (workflow.py:321 -> synthesis.py:97)

```
workflow.py:321   if not llm.dry_run:
workflow.py:322       self._synth_svc.review()
```

`synthesis.py:97 SynthesisService.review()`:
- Lines 100-103: Check synthesis.md and closing.md exist
- Line 108: `load_template("synthesis_review", transcript_path,
  closing_path, synthesis_path)`
- Line 113: `llm.complete(prompt, timeout=600)` -- reviewer reads all three
  files and checks for evidence gaps, fabrication, missing dissent
- Line 118: `extract_json(raw)` -> `{"status": "APPROVED"|"ISSUES_FOUND",
  "issues": [...]}`
- Lines 120-121: Write `review.json`
- Lines 124-131: Log approval or list issues

### Step 14: Done (workflow.py:176-182 or 304-309)

```
workflow.py:176   print("=== Mission Complete (consensus at turn 4) ===")
workflow.py:178   logger.info(f"Transcript: {session.transcript}")
workflow.py:180   logger.info(f"Synthesis: {synthesis}")
```

Control returns to `app.py:89 workflow.execute()` -> `main()` exits.

### Shortcut: Synthesize-Only Mode

When invoked with `--resume <session> --synthesize-only`:

```
workflow.py:112   if synthesize_only:
workflow.py:118       if closing_file.exists():  # skip finalize
workflow.py:122       else: self._orch_svc.finalize(ctx, "unknown")
workflow.py:125       self._synth_svc.synthesize(ctx.mission_body)   # Step 12
workflow.py:127       self._synth_svc.review()                       # Step 13
workflow.py:135       return
```

### Shortcut: Feedback Mode

When invoked with `--resume <session> --feedback "add examples"`:

```
workflow.py:62    if feedback and state.status == "completed":
workflow.py:63        self._smgr.archive_outputs()     # rename closing.md -> closing-TS.md
workflow.py:107   if feedback:
workflow.py:108       self._smgr.inject_operator_turn(feedback)  # insert as Turn N
workflow.py:109       _save_state("running")
```

Then enters main loop normally (Step 8), with the feedback visible in
transcript for the next orchestrator pick.

---

## 3. Module Responsibilities

| Module | Class | Methods | Single Responsibility |
|--------|-------|---------|----------------------|
| app.py | - | main() | Parse CLI, wire deps, launch pipeline |
| workflow.py | MissionWorkflow | execute, _run_discussion_loop, _finalize_and_synthesize, _check_pause | Loop control + phase transitions |
| orchestrator.py | OrchestratorService | pick_speaker, verify_task, finalize, run_execution_phase, next_round_robin | All orchestrator-driven LLM calls |
| agents.py | AgentService | speak, execute, parse_status_signal | All agent-driven LLM calls |
| synthesis.py | SynthesisService | synthesize, review | Post-discussion synthesis + quality check |
| session_io.py | SessionManager | create, resume, update_state, append_*, archive_outputs, inject_operator_turn, get_transcript_context, truncate_transcript_for_closing | All session filesystem I/O |
| models/ | Agent, Orchestrator, Session, MissionContext | (dataclasses) | Pure data structures |
| llm/llm_provider.py | LLMProvider (ABC) | complete, stream | Abstract base -- stream returns None if unsupported |
| llm/claude_cli.py | ClaudeCLI(LLMProvider) | complete, stream | Concrete provider wrapping `claude -p` CLI |
| llm/llm_provider_factory.py | LLMProviderFactory | create(provider, model, dry_run) | Factory for constructing providers by name |
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

**O - Open/Closed**: New LLM providers inherit LLMProvider ABC and register
in LLMProviderFactory -- no existing code modified. New orchestration
strategies can subclass OrchestratorService.

**L - Liskov Substitution**: All LLMProvider subclasses must implement
complete() and stream(). stream() returns int (exit code) or None if
unsupported -- callers check `rc is not None`.

**I - Interface Segregation**: LLMProvider contract has both complete() and
stream(). Providers that don't support streaming return None from stream()
rather than raising -- callers degrade gracefully.

**D - Dependency Inversion**: All services typed against LLMProvider (ABC),
never ClaudeCLI. Construction via LLMProviderFactory in app.py. No module
outside forge/llm/ and forge/app.py references a concrete provider.

---

## 6. LLM Provider Design

### Problem Solved

The original `forge/llm/llm.py` mixed interface and implementation in one
file. `LLMProvider` was a Protocol with only `complete()` -- `stream()` was
ClaudeCLI-specific, checked via `hasattr()` in callers. All service type
hints used `ClaudeCLI` concretely, violating Dependency Inversion.

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
    def model(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def dry_run(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def complete(self, prompt: str, *,
                 label: str = "",
                 timeout: int = 600,
                 max_retries: int = 3) -> str:
        """Send prompt, return response text. Empty string on failure."""
        raise NotImplementedError

    @abstractmethod
    def stream(self, prompt: str, *,
               label: str = "",
               timeout: int = 1800,
               max_retries: int = 3) -> int | None:
        """Send prompt with streaming output.
        Return exit code (0 = success), or None if unsupported.
        """
        raise NotImplementedError
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
    def complete(...) -> str:        # subprocess.run with retry loop
    def stream(...) -> int | None:   # capture_output=False, returns exit code
```

### Caller Changes

All type hints change from `ClaudeCLI` to `LLMProvider`:
- `OrchestratorService.__init__(self, llm: LLMProvider, ...)`
- `AgentService.__init__(self, llm: LLMProvider, ...)`
- `SynthesisService.__init__(self, llm: LLMProvider, ...)`
- `MissionWorkflow.__init__(self, ..., llm: LLMProvider, ...)`

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
  |-- MissionWorkflow(smgr, ctx, llm, orch_svc, agent_svc, synth_svc)
  +-- workflow.execute(...)
```

No module outside `forge/llm/` and `forge/app.py` ever references `ClaudeCLI`
directly. All business logic depends on the `LLMProvider` abstraction.
