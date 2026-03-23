# Framework Evaluation: LangChain vs Google ADK vs LiteLLM

Date: 2026-03-23

## 1. Background

open-foundry currently uses `claude -p` subprocess calls as its sole LLM
backend. To support multi-model (OpenAI, Anthropic, Gemini, Azure, local
models), we evaluated three framework options for the API backend layer:

1. **LangChain** -- the most popular LLM framework
2. **Google ADK** (Agent Development Kit) -- Google's agent framework with
   LiteLLM integration
3. **LiteLLM** -- lightweight API translation layer (100+ providers)

This report documents why LangChain was rejected, the strengths and weaknesses
of Google ADK, and the recommended direction.

---

## 2. LangChain: Why Not

### 2.1 Control Flow Inversion

forge.py owns the main loop. It decides who speaks next (via orchestrator),
constructs prompts, manages transcript windowing (last 7 turns), and
coordinates the evidence-first protocol. LangChain's `AgentExecutor` and
chain abstraction want to own this loop themselves.

Using LangChain would require either:
- Surrendering the main loop to LangChain (losing forge.py's deliberation
  design)
- Fighting against the framework to keep control (constant workarounds)

Neither option is acceptable. open-foundry is an orchestrator, not an
"application built on top of a framework."

### 2.2 Abstraction Leakage and Debug Difficulty

When an LLM call fails inside LangChain, the stack trace passes through
multiple abstraction layers: Chain -> Agent -> LLM -> OutputParser -> Memory.
Debugging a tool-calling format mismatch between providers requires
understanding LangChain's internal dispatch, not just the provider's API.

In practice this means 3-5x longer debug cycles compared to direct API
calls. For a project that needs to support heterogeneous providers (each with
their own tool-calling format), this opacity is a liability.

### 2.3 API Instability

LangChain has undergone 2+ major breaking changes in the 18 months from
late 2024 to early 2026. The split into `langchain-core`, `langchain-community`,
and per-provider packages (`langchain-openai`, `langchain-anthropic`) means
dependency management is an ongoing tax.

As of early 2026 the project has 3000+ open issues on GitHub. Community
sentiment has shifted noticeably -- "LangChain tax" is a common complaint
in developer forums.

### 2.4 Dependency Weight

LangChain pulls in a large dependency tree. open-foundry's orchestrator
(`forge.py`) is currently stdlib-only Python with zero external dependencies.
Adding LangChain would dramatically increase the install surface and potential
for version conflicts.

### 2.5 Conclusion on LangChain

LangChain is designed for a different use case: building LLM-powered
applications where the framework manages the agent lifecycle. open-foundry
needs a thin translation layer, not a framework. The cost/benefit ratio is
unfavorable.

---

## 3. Google ADK: Honest Evaluation

### 3.1 Project Health (as of 2026-03-23)

| Metric              | Value                             |
|----------------------|-----------------------------------|
| GitHub Stars         | 18.5k                             |
| Contributors         | 257                               |
| Forks                | 3.1k                              |
| License              | Apache 2.0                        |
| Current Version      | v1.27.2                           |
| Total Releases       | 44                                |
| Release Cadence      | Bi-weekly                         |
| Open Issues          | 399                               |
| Closed Issues        | 1,942                             |
| Issue Close Rate     | 83%                               |
| Multi-language SDKs  | Python, JavaScript, Go, Java      |

### 3.2 Strengths

**LiteLLM Integration is First-Class.**
ADK officially supports LiteLLM via `google.adk.models.lite_llm.LiteLlm`.
This means one line of code switches between providers:

```python
from google.adk.models.lite_llm import LiteLlm
agent = LlmAgent(model=LiteLlm(model="openai/gpt-4o"), ...)
agent = LlmAgent(model=LiteLlm(model="anthropic/claude-sonnet-4-20250514"), ...)
```

LiteLLM-related bugs are actively fixed in every release (v1.22 through
v1.27 all contain LiteLLM-specific fixes).

**Active Maintenance.**
Google has dedicated maintainers. Issues get triaged with component labels
(core, tools, services, models, mcp, eval, tracing, web) and assigned to
specific engineers. Security issues are handled promptly (CVE-2025-62727
patched in v1.21.0).

**Rich Feature Set.**
Built-in evaluation framework, OpenTelemetry tracing, MCP tool support,
A2A (Agent-to-Agent) protocol, workflow agents (SequentialAgent, ParallelAgent,
LoopAgent), and deployment tools for Cloud Run and Vertex AI.

**Post-1.0 Stability.**
Since 1.0 (June 2025), only 3 breaking changes in 9 months -- all in
peripheral features (BigQuery plugin tracing, CredentialManager signature,
minimum Python version). The core Agent/Model API has been stable.

**Community.**
Community calls, community repo (adk-community), GitHub Discussions, and
active Reddit presence. This is not an abandoned side project.

### 3.3 Weaknesses

**Architectural Mismatch with open-foundry (the "Fan Ke Wei Zhu" Problem).**

ADK's design assumes it owns the agent lifecycle:

```
ADK's world:  Runner -> Session -> Agent -> Model -> Tools
forge.py:     main loop -> orchestrator_pick -> agent_speak -> call_llm
```

Using ADK's full stack means surrendering forge.py's core design:
- ADK's `Runner.run_async()` replaces forge.py's main loop
- ADK's `transfer_to_agent` lets the LLM pick the next speaker; forge.py
  uses an orchestrator role for deliberate speaker selection
- ADK's `SessionService` replaces forge.py's transcript/notes/state.json
  system
- ADK's context management replaces forge.py's 7-turn windowing strategy

This is the same control-flow-inversion problem as LangChain, just with
better engineering quality.

**If you only use `LiteLlm` class without `LlmAgent`/`Runner`, you import
the entire ADK dependency tree for a single wrapper class.** This is
disproportionate. ADK depends on `google-genai`, `pydantic`, `fastapi`,
`opentelemetry-*`, `httpx`, `authlib`, and others. For one wrapper class,
the `litellm` package alone (a single dependency) provides the same
functionality.

**Rapid Iteration Means Churn.**
44 releases in ~10 months is impressive velocity, but also means the API
surface is still evolving. The `v1.27.1` hotfix (rolling back a change that
broke LlmAgent creation) shows that even point releases can introduce
regressions. For a project that values stability and minimal dependencies,
this pace is a risk factor.

**Google Cloud Gravity.**
While not locked to Google Cloud, many ADK features (VertexAiSessionService,
Agent Engine deployment, BigQuery toolsets, GCS artifacts) pull toward the
Google ecosystem. open-foundry is cloud-agnostic by design.

### 3.4 Conclusion on Google ADK

ADK is a well-engineered, actively maintained framework. It is the right
choice for building an "agent application" where ADK manages the lifecycle.
But open-foundry is an "agent orchestrator" that must own its own loop.

Using ADK for open-foundry would be like using Rails to build a custom
web server -- the framework is excellent, but the use case demands lower-level
control.

---

## 4. Recommended Direction: Direct LiteLLM

Use the `litellm` package directly (without ADK wrapper) as a thin
translation layer:

```python
import litellm

response = litellm.completion(
    model="anthropic/claude-sonnet-4-20250514",
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ],
    tools=[...],
)
```

### Why This Fits

| Concern                    | LiteLLM Direct          |
|----------------------------|-------------------------|
| Control flow               | forge.py keeps its loop |
| Dependency weight           | Single package          |
| Multi-provider support      | 100+ providers          |
| Tool calling normalization  | OpenAI-compatible       |
| Streaming                  | Supported               |
| Debug transparency          | Direct API, thin layer  |

### Migration Path

1. Extract `call_claude()` into a backend abstraction
2. Add `LiteLLMBackend` that calls `litellm.completion()`
3. Keep `CLIBackend` for Claude Code's agentic features (WebSearch, file
   I/O, terminal execution)
4. Route based on configuration: CLI backend for agentic tasks, API backend
   for structured deliberation

---

## 5. Summary Table

| Criterion               | LangChain    | Google ADK        | LiteLLM Direct    |
|--------------------------|-------------|-------------------|--------------------|
| Control flow preserved   | No          | No (full stack)   | Yes                |
| Dependency weight        | Heavy       | Heavy             | Light              |
| Multi-model support      | Good        | Good (via LiteLLM)| Good               |
| Debug transparency       | Poor        | Medium            | Good               |
| API stability            | Poor        | Good              | Good               |
| Community health         | Declining   | Growing           | Growing            |
| Fit for open-foundry     | Poor        | Poor (mismatch)   | Good               |

---

## 6. Appendix: When ADK Would Make Sense

If open-foundry ever evolves toward:
- Deploying individual agents as microservices (A2A protocol)
- Using Google Cloud's Vertex AI for agent hosting
- Needing built-in evaluation pipelines
- Building a web UI for agent interaction

...then ADK becomes worth reconsidering. The key question is always:
"Does the framework's lifecycle model match your orchestration model?"
For deliberation panels, the answer is currently no.
