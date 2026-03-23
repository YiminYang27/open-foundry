# CLI Backend Support Analysis for open-foundry

Date: 2026-03-23

## 1. Context

open-foundry's orchestrator (`forge.py`) drives agent discussions by spawning
CLI subprocesses. The current implementation calls `claude -p -` -- piping a
prompt via stdin and capturing stdout as the agent's response. Each call runs
with `--dangerously-skip-permissions` to enable fully autonomous file I/O,
terminal commands, and web search.

This report evaluates four CLI candidates as potential backends:

1. Claude Code CLI (`claude`)
2. Gemini CLI (`gemini`)
3. OpenAI Codex CLI (`codex`)
4. GitHub Copilot CLI (`gh copilot`)

---

## 2. Summary Table

| Capability | Claude Code CLI | Gemini CLI | Codex CLI | GitHub Copilot CLI |
|------------|:-:|:-:|:-:|:-:|
| **Viable for open-foundry** | Yes (current) | Yes | Partial | No |
| Non-interactive pipe mode | `claude -p -` | `gemini -p` | `codex -q` | N/A |
| Stdin prompt input | Yes | Yes | Yes | No |
| Stdout capture | Yes, clean text | Yes, clean text | Yes | N/A |
| File read/write | Yes | Yes | Yes (sandboxed) | No |
| Terminal command exec | Yes | Yes | Yes (sandboxed) | Explain only |
| Web search | Yes (WebSearch tool) | Yes (Google Search) | No | No |
| Skip permissions flag | `--dangerously-skip-permissions` | `--sandbox=none` | `--full-auto` | N/A |
| Model selection | `--model opus/sonnet/haiku` | `--model gemini-2.5-pro` | `--model o3/o4-mini` | N/A |
| Open source | No | Yes (Apache 2.0) | Yes (Apache 2.0) | No |
| Cost model | Claude subscription or API | Free (Google AI Studio) | ChatGPT plan or API key | Copilot subscription |
| Hidden system prompt quality | Excellent (agentic) | Good (agentic) | Good (coding-focused) | N/A |

---

## 3. Detailed Analysis

### 3.1 Claude Code CLI -- Fully Supported (Current Backend)

**Invocation pattern:**
```bash
echo "prompt" | claude -p - --model sonnet --dangerously-skip-permissions
```

**Why it works perfectly for open-foundry:**

- **Pipe mode (`-p -`)** is a first-class feature. Reads prompt from stdin,
  writes response to stdout, exits. Designed to be wrapped by scripts.
- **Hidden system prompt** includes full agentic tool definitions: file I/O,
  terminal execution, WebSearch, WebFetch. When forge.py tells the agent
  "use WebSearch to verify data", the agent knows how because the system
  prompt already defines that tool.
- **`--dangerously-skip-permissions`** allows autonomous execution without
  confirmation prompts. Essential for unattended multi-turn discussions.
- **Model override** via `--model` flag maps directly to forge.py's `--model`
  argument.
- **Retry-safe** -- stateless subprocess calls. If a call fails, forge.py
  retries once with a 2-second delay.

**Limitations:**
- Proprietary. Requires Anthropic account.
- Token costs can be significant for 40-turn discussions with Opus.
- The hidden system prompt is not user-configurable -- you get whatever
  Anthropic ships.

**Assessment: Production-ready. No changes needed.**

---

### 3.2 Gemini CLI -- Strongly Recommended for Support

**Invocation pattern:**
```bash
echo "prompt" | gemini -p --model gemini-2.5-pro --sandbox=none
```

**Why it should work for open-foundry:**

- **Pipe mode (`-p`)** exists and behaves similarly to Claude's -- stdin in,
  stdout out, exit on completion.
- **Google Search integration** is built into the CLI's agentic runtime.
  Agents can search the web natively, satisfying open-foundry's evidence-first
  protocol. This is the critical differentiator vs Codex.
- **File I/O and terminal access** available when sandbox is disabled
  (`--sandbox=none`).
- **Free tier** via Google AI Studio means zero marginal cost for
  experimentation. This dramatically lowers the barrier to entry.
- **Open source** (Apache 2.0) -- the CLI codebase is inspectable, and the
  system prompt behavior is more transparent than Claude's.
- **Model selection** supports the full Gemini model family including
  Gemini 2.5 Pro and Flash variants.

**Required integration work:**
- Add a `GeminiCLIBackend` that constructs the subprocess command with
  Gemini-specific flags.
- Test JSON output reliability for orchestrator speaker selection (Gemini's
  structured output compliance may differ from Claude's).
- Verify that `--sandbox=none` grants sufficient file access for notes/
  read/write operations.
- Map forge.py's `--model` values to Gemini model names.

**Risks:**
- Gemini's function calling and tool use behavior may produce different
  output formatting than Claude (e.g., different citation styles, different
  WebSearch result formatting in responses).
- Rate limits on the free tier may throttle long discussions.
- The hidden system prompt's agentic quality, while good, has not been
  battle-tested at the same scale as Claude Code's.

**Assessment: High priority. The combination of free tier + web search +
open source makes this the single most impactful backend to add.**

---

### 3.3 OpenAI Codex CLI -- Partial Support, Significant Gaps

**Invocation pattern:**
```bash
echo "prompt" | codex -q --model o3 --full-auto
```

**What works:**

- **Quiet mode (`-q`)** suppresses interactive UI and outputs results to
  stdout. Can accept piped input.
- **`--full-auto`** mode skips all permission confirmations, equivalent to
  Claude's `--dangerously-skip-permissions`.
- **File I/O** works within the local project directory.
- **Terminal command execution** is supported in sandbox.
- **Open source** (Apache 2.0), large community (66k+ GitHub stars, 400+
  contributors), actively developed (Rust rewrite, 640+ releases).
- **Model selection** supports OpenAI models (o3, o4-mini, codex-mini).

**What does NOT work:**

- **No web search capability.** This is the dealbreaker for finance and
  research discussions. The Codex CLI was designed for coding tasks in
  sandboxed environments. The cloud Codex product recently added internet
  access, but the CLI version has no built-in search tool. An agent told to
  "use WebSearch to find current CPI data" will either hallucinate the data
  or report that it cannot search.
- **Coding-focused system prompt.** The hidden system prompt is optimized for
  software engineering: reading code, writing patches, running tests. It does
  not include instructions for structured deliberation, evidence verification,
  or multi-perspective analysis. This means agent behavior quality for
  non-coding discussions (finance, geopolitics) will be noticeably worse.
- **Stdout capture reliability.** In quiet mode, Codex may still emit
  progress indicators or status messages mixed with the actual response.
  Parsing requires more robust output extraction than Claude's clean stdout.

**Required integration work:**
- Add a `CodexCLIBackend` with appropriate flag mapping.
- Implement robust output parsing to separate response text from status noise.
- For non-coding discussions, consider prepending a deliberation-focused
  instruction to the user prompt to partially compensate for the
  coding-oriented system prompt.
- Document clearly that web search is unavailable -- users must understand
  that evidence-first protocol cannot be enforced.

**Viable use cases in open-foundry:**
- **Software architecture discussions** -- agents exploring a codebase,
  reviewing API design, debating implementation strategies. Here the
  coding-focused system prompt is actually an advantage.
- **Orchestrator-only** -- use Codex CLI for the speaker selection calls
  (JSON output, no tools needed) while using Claude or Gemini for agent
  responses.

**Assessment: Support as a secondary backend, clearly documented as
limited to software-domain discussions. Not suitable for finance or
research topics requiring live data.**

---

### 3.4 GitHub Copilot CLI -- Not Viable

**Invocation pattern:**
```bash
gh copilot suggest "prompt"
gh copilot explain "prompt"
```

**Why it cannot work for open-foundry:**

1. **No pipe mode.** `gh copilot` is an interactive assistant that suggests
   shell commands or explains code. It does not accept arbitrary prompts via
   stdin and return freeform text via stdout. There is no `-p` equivalent.

2. **No agentic runtime.** Copilot CLI cannot read/write files, execute
   arbitrary commands, or search the web. It is a Q&A tool scoped to shell
   command suggestion and explanation. It has no tool use, no function
   calling, no autonomous execution capability.

3. **Not a general-purpose LLM interface.** Unlike `claude`, `gemini`, and
   `codex`, which expose the full model capability through a CLI, `gh copilot`
   is a purpose-built wrapper around a narrow set of features. The underlying
   model (GPT-4 variant) is capable, but the CLI does not expose that
   capability in a programmable way.

4. **No model selection.** You cannot choose which model runs behind
   `gh copilot`. There is no `--model` flag.

5. **Output format is not machine-parseable.** Responses include interactive
   prompts, confirmation dialogs, and formatted output that cannot be
   reliably captured as clean text.

6. **No skip-permissions equivalent.** Every suggestion requires user
   confirmation in the terminal. There is no way to run it unattended.

**Could Copilot evolve to be viable?**

Unlikely in the current architecture. GitHub Copilot's strategy is IDE
integration (VS Code, JetBrains, Xcode) and cloud-based code review
(Copilot Code Review on PRs). The CLI tool is a minor utility, not a
platform. Microsoft/GitHub has shown no indication of building an agentic
CLI runtime comparable to Claude Code or Codex.

If GitHub were to ship a `copilot agent` command with pipe mode, file
access, and tool use, it could become viable. But as of March 2026, this
does not exist and is not on any public roadmap.

**Assessment: Not supported. No technical path to integration exists.**

---

## 4. Integration Architecture

```
forge.py
  |
  +-- CLIBackend (interface)
  |     |
  |     +-- call(prompt, model, skip_perms, timeout) -> str
  |     +-- supports_web_search -> bool
  |     +-- supports_file_io -> bool
  |
  +-- ClaudeCLIBackend
  |     cmd: ['claude', '-p', '-', '--model', model,
  |            '--dangerously-skip-permissions']
  |     web_search: True
  |     file_io: True
  |
  +-- GeminiCLIBackend
  |     cmd: ['gemini', '-p', '--model', model,
  |            '--sandbox=none']
  |     web_search: True
  |     file_io: True
  |
  +-- CodexCLIBackend
        cmd: ['codex', '-q', '--model', model,
               '--full-auto']
        web_search: False
        file_io: True
```

The `supports_web_search` flag allows forge.py to warn users when starting
a discussion that requires evidence-first protocol with a backend that
cannot search. It also allows the orchestrator to skip evidence-gating
rules when search is unavailable.

---

## 5. Prioritized Roadmap

| Priority | Backend | Effort | Impact |
|----------|---------|--------|--------|
| 1 (done) | Claude Code CLI | -- | Baseline, production-ready |
| 2 (high) | Gemini CLI | Medium | Free tier + web search = largest new user pool |
| 3 (medium) | Codex CLI | Medium | Software-domain discussions, large OSS community |
| 4 (skip) | GitHub Copilot | -- | No technical path. Revisit if architecture changes |

---

## 6. Beyond CLI: The API Backend Path

All three viable CLIs share one constraint: they bundle a hidden system
prompt that the user cannot modify. This means:

- Agent behavior nuances are controlled by the CLI vendor, not by
  open-foundry
- Quality differences between CLIs are partly due to system prompt
  differences, not just model capability
- Users cannot bring their own model (DeepSeek, Llama, Mistral, etc.)

The long-term solution is an API backend with open-foundry's own system
prompt and lightweight tool layer (web_search via Tavily/SerpAPI,
read_file, write_file). This is a separate workstream documented in
the backend architecture proposal. CLI backends remain the "batteries
included" path; API backend is the "bring your own model" path.
