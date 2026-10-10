# Which Python agent frameworks could drive Pickled's agent?

Research for [#4](https://github.com/KianMeijers/Pickled/issues/4), part of the v1 architecture map ([#1](https://github.com/KianMeijers/Pickled/issues/1)). Checked on 2026-10-10 against official docs, PyPI and GitHub.

## Gist

Pydantic AI fits Pickled best. It talks to any OpenAI-compatible endpoint through a `base_url`, has typed tools and structured output, includes a Starlette/FastAPI adapter that streams a run to a web UI, and has the best test doubles (`TestModel`, `FunctionModel`, `Agent.override`). The same `Agent` object runs in a request handler or a background job. Writing our own loop is the main alternative and teaches the most. A good plan is to write a short throwaway loop first so the mechanics are clear, then build the product on Pydantic AI.

## What Pickled needs

From the ticket: works with any provider or an OpenAI-compatible endpoint (Runware), tool calling, structured output, streaming to a web UI, the same agent in a background job, testability with mock models, maturity, and how much it teaches about real-world agent engineering. Pickled has one Household, runs locally, and is Python 3.14. The repo currently depends on `anthropic` and `pydantic-settings` (`pyproject.toml`).

### Context on Runware (provider-side, not this ticket's question)

Runware documents an OpenAI-compatible **Chat Completions** endpoint at `https://api.runware.ai/v1/chat/completions`, with streaming (`stream: true`, `stream_options.include_usage`). It also lists `/v1/messages` (Anthropic format). The page does **not** mention tools, `tool_choice`, `response_format`/JSON schema, or the OpenAI **Responses** API ([Runware: OpenAI compatibility](https://runware.ai/docs/platform/openai)). So the framework has to work over plain Chat Completions, and tool/structured-output support depends on each model. The sibling provider ticket owns this question.

## Candidates

| | Pydantic AI | OpenAI Agents SDK | LangGraph (+ LangChain `create_agent`) | smolagents | Own loop (on `openai` SDK) |
|---|---|---|---|---|---|
| Version / status (PyPI, 2026-10-10) | `pydantic-ai` 2.55.0, "Production/Stable", Python ≥3.11, 3.14 classifier | `openai-agents` 0.23.1, still 0.x, 3.14 classifier | `langgraph` 1.2.14, "Production/Stable" | `smolagents` 1.26.0, last release 2026-05-29 | `openai` 3.28.0 |
| GitHub (stars, last push, license) | 20.5k, 2026-10-10, MIT | 30.0k, 2026-10-08, MIT | 43.0k, 2026-10-10, MIT | 29.8k, 2026-10-06, Apache-2.0 | n/a |
| OpenAI-compatible endpoint | Yes: `OpenAIChatModel` + `OpenAIProvider(openai_client=AsyncOpenAI(base_url=...))`; also native Anthropic, etc. | Yes, but OpenAI-first: needs `OpenAIChatCompletionsModel` or `set_default_openai_api("chat_completions")`, because many providers lack Responses. LiteLLM/Any-LLM adapters are "best-effort, beta" | Yes, through LangChain chat model integrations (`"provider:model"` strings or a model instance) | Yes, through `OpenAIModel`, `LiteLLMModel(api_base=...)` and others | Yes, natively |
| Tool calling | Typed Python functions, schemas from signatures and docstrings, deps injection | `@function_tool`, handoffs, hosted tools (OpenAI-only) | LangChain tools; the graph lets you control the loop exactly | `ToolCallingAgent` (JSON) or `CodeAgent` (LLM writes Python that runs locally or in a sandbox) | You write the schemas, dispatch, error handling and limits |
| Structured output | First-class (`output_type=` a Pydantic model, validated, retries) | `output_type`; docs warn some non-OpenAI providers reject `json_schema` | `response_format=` a Pydantic model → `structured_response` | `final_answer_checks` only; no typed output model | Pydantic + `response_format` or a "final answer" tool, all by hand |
| Streaming to a web UI | `run_stream_events()`, plus `VercelAIAdapter` / `AGUIAdapter` with `dispatch_request()` that return a Starlette SSE response | `Runner.run_streamed()` → `stream_events()`; raw events use the Responses-event shape; you build the SSE | `stream_events(version="v3")` / stream modes; you build the SSE | Step streaming; built mainly for `GradioUI`; sync-first | You map deltas to SSE yourself |
| Same agent in a background job | Yes, `agent.run()` / `run_sync()`. Optional durable execution (Temporal, DBOS, Prefect, Restate, …) | Yes, `Runner.run()`. Temporal integration exists | Yes, and the strongest story: checkpointers and resume are built in | Yes (`agent.run`) | Yes, a plain function |
| Mock models for tests | Best: `TestModel`, `FunctionModel`, `Agent.override`, `ALLOW_MODEL_REQUESTS=False`, `capture_run_messages` | Good: `agents.testing.ScriptedModel`, `assistant_message`, `function_call`, `assert_complete()` | Good: `GenericFakeChatModel` scripts `AIMessage`s with `tool_calls`; `InMemorySaver` | Weak: no documented fake model; you subclass a model | Whatever you build (a fake client is simple) |
| Observability | OpenTelemetry built in (Logfire is optional) | Tracing **uploads to OpenAI by default**; without an OpenAI key you get 401s and must turn it off or swap the processor | LangSmith-oriented; OTel possible | Logs / `agent.logs` | DIY |
| Dependency weight | `pydantic-ai-slim[openai]` is small (pydantic, httpx, otel-api) | Pulls in mcp, starlette, websockets, requests… | langchain-core, checkpoint, sdk, prebuilt | huggingface-hub, jinja2, pillow, rich | `openai` only |
| What it teaches | The agent loop as typed messages, tool schemas, output validation and retries, deps injection, eval-style testing; it hides the loop but can expose it (`agent.iter()`) | Handoffs, guardrails and sessions in OpenAI's style; partly tied to OpenAI's platform | Explicit state machines, checkpointing, human-in-the-loop, durability; most to learn | Code-acting agents, an interesting idea that doesn't fit Pickled | Everything: message bookkeeping, tool dispatch, partial-JSON streaming, retries, limits, cost tracking |

Sources: PyPI JSON for each package; GitHub repo metadata via `gh api repos/...`; docs linked below.

## Notes per candidate

### Pydantic AI
- OpenAI-compatible endpoints: wrap an `AsyncOpenAI(base_url=..., api_key=...)` in `OpenAIProvider` and pass that to `OpenAIChatModel`. The provider also reads `OPENAI_BASE_URL` ([models/openai](https://pydantic.dev/docs/ai/models/openai/), [providers API](https://pydantic.dev/docs/ai/api/pydantic-ai/providers/)). A native Anthropic model is also available (the `anthropic` extra), which matters if we ever use Runware's `/v1/messages`.
- UI streaming: `VercelAIAdapter.dispatch_request(request, agent=agent)` inside a Starlette/FastAPI route returns the streaming response. `AGUIAdapter` covers AG-UI. Lower-level options: `run_stream_native()`, `encode_stream()`, `streaming_response()` ([UI overview](https://pydantic.dev/docs/ai/integrations/ui/overview/)).
- Testing: `TestModel` calls every tool and then returns schema-valid output. `FunctionModel` lets a test script each turn. `Agent.override(model=...)` swaps the model without touching call sites. `models.ALLOW_MODEL_REQUESTS = False` blocks real calls ([testing guide](https://pydantic.dev/docs/ai/guides/testing/)).
- Durable execution: Temporal, DBOS, Prefect, Restate and AWS Lambda integrations are co-maintained, plus a builder API for other engines ([durable execution](https://pydantic.dev/docs/ai/integrations/durable_execution/overview/)). Pickled doesn't need this in v1, but jobs could adopt it later.
- Maturity risk: very fast release pace (v2.0.0b1 was 2026-05-21 and v2.55.0 came 2026-10-09, roughly weekly minors). Compatibility notes in releases show behaviour changes in minors, e.g. 2.53.0 changed `ConcurrencyLimitedModel` and 2.52.0 changed the Anthropic default `max_tokens` ([releases](https://github.com/pydantic/pydantic-ai/releases)). Pin the version and read release notes when upgrading.

### OpenAI Agents SDK
- Built around OpenAI's Responses API. For other providers the docs say to use Chat Completions, because "many LLM providers still do not support the Responses API". Responses-only fields are silently dropped unless `strict_feature_validation=True`. Tracing uploads to OpenAI and fails with 401 without an OpenAI key ([models doc](https://openai.github.io/openai-agents-python/models/)).
- Streaming: `Runner.run_streamed()` → `stream_events()`, with raw Responses events plus run-item events ([streaming](https://openai.github.io/openai-agents-python/streaming/)).
- Testing: `agents.testing.ScriptedModel` with `assistant_message()` / `function_call()` and `assert_complete()` ([testing](https://openai.github.io/openai-agents-python/testing/)).
- Still 0.x after 123 releases. Workable, but on Runware we would always be on the secondary path.

### LangGraph
- Describes itself as a "low-level orchestration framework and runtime for building, managing, and deploying long-running, stateful agents". It can be used without LangChain ([overview](https://docs.langchain.com/oss/python/langgraph/overview)). The quick way to build a tool agent is LangChain's `create_agent` (model string or instance, `response_format=`, `stream_events`), which runs on LangGraph ([agents](https://docs.langchain.com/oss/python/langchain/agents)).
- Testing with `GenericFakeChatModel`, which can emit `tool_calls` ([unit testing](https://docs.langchain.com/oss/python/langchain/test/unit-testing)).
- More than Pickled needs: a single chat agent plus a few jobs doesn't need a graph runtime, and LangChain's abstraction layers add surface area to learn that doesn't carry over to other stacks.

### smolagents
- Its main feature is `CodeAgent`, where the LLM writes Python that runs in a local restricted interpreter or a sandbox (E2B, Docker, Modal, Blaxel). `ToolCallingAgent` is the JSON tool-calling variant ([guided tour](https://huggingface.co/docs/smolagents/guided_tour)).
- No typed structured-output model and no documented test model. Its UI story centres on Gradio. Releases have slowed (1.26.0 on 2026-05-29). Not a good fit.

### Own loop
- Over `openai.AsyncOpenAI(base_url=...)`: about 150–300 lines for the loop, tool registry (Pydantic models → JSON schema), dispatch, max-steps limit, streaming of text and tool-call deltas, and a fake client for tests.
- Teaches the most and adds no dependency. The downside is that every production concern (retries on invalid tool args, output validation, usage accounting, OTel, UI protocol) becomes our code to maintain. Pydantic AI already solves each of these, and its solutions are worth studying.
- The existing `anthropic` dependency's tool runner (`client.beta.messages.tool_runner`) is a Claude-API helper and still in beta ([tool runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)). It only helps if Pickled talks to an Anthropic-format endpoint.

## Recommendation

**Use Pydantic AI (`pydantic-ai-slim[openai]`, pinned) as Pickled's agent framework.** Point `OpenAIChatModel` at Runware's base URL, define Pickled's tools as typed functions with a deps object (DB, Household), use `output_type` for Meal Plans and Shopping Lists, serve the chat through `VercelAIAdapter` (or AG-UI) in a Starlette/FastAPI route, and call `agent.run()` from scheduled jobs. Test with `TestModel`/`FunctionModel` and `ALLOW_MODEL_REQUESTS = False`.

For learning: write a short throwaway "own loop" spike (one tool, streaming, a fake client) before adopting Pydantic AI. It costs about a day and makes every Pydantic AI abstraction readable. Use `agent.iter()` to step through the graph when debugging.

Second choice: own loop, if the owner values learning over speed. Not recommended: OpenAI Agents SDK (OpenAI-first, tracing defaults, 0.x), LangGraph (more machinery than one chat agent needs), smolagents (code-acting paradigm, weak typing and testing).

## Open questions this raises

1. **Does Runware's Chat Completions endpoint support `tools`, `tool_choice` and `response_format: json_schema` for the models we'd use?** Its docs don't say. If structured output isn't supported, Pydantic AI can fall back to tool-based output, but tool calling itself is a hard requirement (sibling provider ticket).
2. **Which UI stream protocol: Vercel AI Data Stream or AG-UI?** This depends on the frontend choice (e.g. the Vercel AI SDK `useChat` hook vs. something lighter). Affects the web UI ticket.
3. **Do background jobs need durable execution (Temporal/DBOS/Prefect), or is a plain scheduler + `agent.run()` enough for v1?** Probably the latter, but it should be decided alongside the scheduler choice.
4. **How do we handle Pydantic AI's release pace?** Pin an exact version and upgrade on purpose. The `anthropic` dependency in `pyproject.toml` may become unnecessary.
