# What Runware offers for LLM inference

Research for issue #3. Sources were checked on 2026-10-10 and are all first-party: Runware's docs, the machine-readable model index, per-model OpenAPI schemas, the pricing page, and PyPI. Runware adds models often, so check prices and model IDs again before relying on them.

## TL;DR

- Runware offers about 50 LLMs through **three ways in**:
  1. a **native task API** (`POST https://api.runware.ai/v1`, `taskType: "textInference"`);
  2. an **OpenAI Chat Completions-compatible** endpoint (`/v1/chat/completions`);
  3. an **Anthropic Messages-compatible** endpoint (`/v1/messages`). [Compatible APIs]
- The Anthropic endpoint passes the request body **to Anthropic unchanged**. Tool use, thinking, prompt caching and streaming therefore work as Anthropic documents them. You use it with the official `anthropic` Python SDK by changing `base_url` and `auth_token`. [Compatible APIs]
- The **native API is a poor fit for a tool-using agent**. Its published message schema allows only `user`/`assistant` roles with plain string content. No documented field carries a tool result back to the model. [Sonnet 4.6 schema]
- The newest frontier models (Claude Sonnet 5.5, Opus 5.5, Fable 5.1, GPT-6, Grok 4.7 and others) are **"compatible-only"**. You can reach them only through the OpenAI or Anthropic compatible endpoints, not through the native API. [Pricing page data, Sonnet 5.5 model page]
- **Recommendation:** keep the `anthropic` SDK that `pyproject.toml` already lists and point it at Runware's `/v1/messages`. Use **Claude Sonnet 5.5** (`anthropic:claude@sonnet-5.5`, $2 / $10 per 1M input/output tokens, 1M context) for both chat and background jobs. Details are under [Recommendation](#recommendation).

## Access methods

| | Native API | OpenAI-compatible | Anthropic-compatible |
| --- | --- | --- | --- |
| Endpoint | `POST https://api.runware.ai/v1` (JSON array of tasks) | `POST https://api.runware.ai/v1/chat/completions` | `POST https://api.runware.ai/v1/messages` |
| Auth | `Authorization: Bearer <key>` | same | same (Anthropic SDK: pass key as `auth_token`, `base_url="https://api.runware.ai"`) |
| Models | Those with a native schema (`status: live`) | ~50 LLMs, listed on the Compatible APIs page | Claude models only (Fable 5 / 5.1, Haiku 4.5, Opus 4.7 / 4.8 / 5 / 5.5, Sonnet 4.6 / 5 / 5.5) |
| Model ID | Runware AIR (`anthropic:claude@sonnet-4.6`) | AIR | AIR, Runware id (`anthropic-claude-opus-5-5`) or Anthropic's own name |
| Streaming | `deliveryMethod: "stream"` (SSE, Runware format) | `stream: true`, SSE identical to OpenAI's | `stream: true`, Anthropic's own SSE events |
| Async / webhooks | Yes (`deliveryMethod: "async"`, `webhookURL`, polling) | No | Not documented |
| Cost in response | `includeCost: true` | `usage.cost` in the usage chunk when `stream_options.include_usage` is set | Not documented |
| Python client | `runware-sdk` (official) | `openai` SDK | `anthropic` SDK |

Sources: [Compatible APIs], [Models API intro], [Streaming].

Notes:
- For the OpenAI endpoint, Runware says "the provider's documentation stays the reference for every parameter" and that the endpoint is "fully compatible with the OpenAI protocol". The page shows streaming and reasoning examples. It **does not show** `tools` or `response_format` examples. [Compatible APIs]
- For the Anthropic endpoint, Runware says: "The request body reaches Anthropic unchanged, so every Messages parameter works as documented, including thinking, prompt caching, tool use and vision." [Compatible APIs]
- The Python example on the Compatible APIs page is literally:
  ```python
  from anthropic import Anthropic
  client = Anthropic(auth_token="your_runware_api_key", base_url="https://api.runware.ai")
  client.messages.create(model="anthropic:claude@opus-5.5", max_tokens=1024, messages=[...])
  ```

## Native `textInference` capabilities

From the per-model OpenAPI schemas (`https://runware.ai/docs/models/<id>/schema.json`) [Model schemas]:

- **Tools.** Most LLMs accept `tools` and `toolChoice`. Exceptions: Gemma 4 31B has neither in its native schema. MiniMax M2.7 and GLM-5.1 have tools but no `inputs`.
  - Tool types: `function`, with `name`, `description` and `schema` (JSON Schema). Anthropic also offers server-side `search` and `codeInterpreter`.
  - `toolChoice` values: `auto`, `any`, `tool`, `none`.
  - A native tool-call response looks like `finishReason: "tools"` plus a `tools: [{id, name}]` array. [MiniMax M3 examples.json]
- **Gap: no way to return tool results.** `messages[].role` is an enum of `user`/`assistant`, `content` is a plain string, and "the final message must use the user role". No `tool` role, tool-result block, or tool-call id field is documented. A multi-turn tool loop therefore cannot be expressed in the published native schema. [Sonnet 4.6 schema]
- **Structured output.** A `jsonSchema` field ("Accepts the OpenAI envelope ({name, schema, strict}) or a bare JSON Schema") exists on only some models: Fable 5, GPT-5.5 and Gemini 3.5 Flash. It is "only honoured when `outputFormat` is JSON". [Fable 5 / GPT-5.5 / Gemini 3.5 Flash schemas]
- **Streaming.** SSE is available for all text models. Chunks carry `delta.text` and `delta.reasoningContent`. The stream ends with `data: [DONE]`. Finish reasons include `tool_calls` and `tool_use`. Cost and usage arrive in the final chunk. [Streaming]
- **Settings vary per model.** Examples: `systemPrompt`, `maxTokens`, `thinkingLevel`, `cache` (scope and TTL for Claude), `temperature` and `topP` (not on Claude).

## Models and prices

Prices are in USD per 1M tokens (input / output / cached input). "Live" means the model has a native schema. "Compat-only" means you can reach it only through `/v1/chat/completions` or `/v1/messages`. Sources: [Model schemas] `info["x-pricing"]` and the [Pricing page] embedded model data.

Strong tool-using candidates:

| Model | AIR ID | Status | Context / max out | In / Out / Cached |
| --- | --- | --- | --- | --- |
| Claude Sonnet 5.5 | `anthropic:claude@sonnet-5.5` | compat-only (released 2026-09-28) | 1M / 128K | $2 / $10 / $0.20 (cache write $2.50) |
| Claude Opus 5.5 | `anthropic:claude@opus-5.5` | compat-only | 1M / 128K | $4 / $20 / $0.20 (cache write $5) |
| Claude Fable 5.1 | `anthropic:claude@fable-5.1` | compat-only | 1M / 128K | $10 / $50 / $0.25 |
| Claude Sonnet 4.6 | `anthropic:claude@sonnet-4.6` | live | 1M (beta) / 64K | $3 / $15 / $0.30 |
| Claude Haiku 4.5 | `anthropic:claude@haiku-4.5` | live | – / 64K | $1 / $5 / $0.10 |
| GPT-6 Sol | `openai:gpt@6-sol` | compat-only | priced in tiers at 272K | $2 / $10 / $0.20 (≤272K) |
| GPT-6 Luna | `openai:gpt@6-luna` | compat-only | priced in tiers at 272K | $0.10 / $0.50 / $0.01 (≤272K) |
| GPT-5.5 | `openai:gpt@5.5` | live | 1.05M / 128K | $5 / $30 / $0.50 |
| Gemini 3.8 Flash | `google:gemini@3.8-flash` | compat-only | – | $0.75 / $3.75 / $0.075 |
| Grok 4.7 | `xai:grok@4.7` | compat-only | priced in tiers at 200K | $2 / $6 / $0.50 (<200K) |
| GLM-5.3 | `zai:glm@5.3` | compat-only | – | $1.20 / $4 / $0.20 |
| MiniMax M3 | `minimax:m3@0` | live | 1M / 512K | $0.30–0.60 / $1.20–2.40 (tiered) |
| DeepSeek-V4.1-Flash | `deepseek:v4.1@flash` | compat-only | 1M | $0.15 / $0.60 / $0.01 |
| GLM-5.3-Flash | `zai:glm@5.3-flash` | compat-only | – | $0.15 / $0.50 / $0.03 |

The [Compatible APIs] page also lists, with no published price found: Claude Opus 5 and Sonnet 5, Kimi K2.6 and K3, DeepSeek V4 Pro and Flash, GLM-5.2, Gemini 3.5 Flash-Lite, 3.6 Flash and 3.7 Flash, GPT-5.6 (Luna/Sol/Terra), GPT-6 Astra, GPT-6.1 Sol, gpt-oss-120b, and others. Context sizes marked "–" were not stated in the sources read.

Billing: pay-as-you-go in USD with no subscription. The balance never expires, and failed generations are not charged. [Pricing]

## Operational notes

- **Rate limits.** Runware sets a per-organization REST limit that "sits far above typical traffic". When a model's queue is full it returns `429` with `Retry-After`, or a `serviceOverloaded` error with `retryAfter`. `503` and `504` are also possible. Upstream providers' limits show up as Runware errors. Runware recommends 2–4 concurrent requests and retrying with backoff. [Rate Limits]
- **Data handling.** "Runware never uses data sent through the API to train or improve models." Zero Data Retention is an enterprise option, and it **does not cover Claude, GPT or Gemini** today. Only certain open models are covered (DeepSeek V4, GLM-5.2/5.3, Kimi K3, Gemma 4, gpt-oss). [ZDR]
- **Python SDKs.** The current official SDK is `runware-sdk` 1.7.2 (async, Python ≥3.11, released 2026-10-09). Its text streaming goes through `client.stream()`. The older `runware` 0.5.x package (repo `runware/sdk-python`) is the legacy SDK; the site's llms.txt still links it. Pickled needs neither if it uses the Anthropic endpoint. [Python SDK docs, PyPI]

## Recommendation

**Access method:** use the **Anthropic Messages-compatible endpoint** through the existing `anthropic` SDK:
```python
Anthropic(auth_token=RUNWARE_API_KEY, base_url="https://api.runware.ai")
```
Reasons:
1. It is the only path where Runware explicitly guarantees tool use, thinking, prompt caching and streaming, by passing the body through to Anthropic.
2. Pickled already depends on `anthropic`. Settings only change from `ANTHROPIC_API_KEY` to a Runware key plus a base URL.
3. It reaches the newest Claude models, which are compat-only.
4. The native API cannot express a tool-result turn in its published schema.

Use the OpenAI-compatible endpoint only if a non-Claude model is wanted later.

**Model:** **Claude Sonnet 5.5** (`anthropic:claude@sonnet-5.5`) as the default for both chat and background jobs. It is Runware's "fast, cost-efficient Claude model for everyday coding, agents, and knowledge work", with tools, adaptive thinking, 1M context and 128K output, and it costs less than Sonnet 4.6.

Rough cost per agent turn with ~20K input tokens (mostly cached system prompt and tools) and 1K output: about $0.01–0.05.

Keep **Claude Opus 5.5** ($4 / $20) as an opt-in for hard weekly planning runs if Sonnet's plans fall short. Make the model ID a setting so this is a config change.

## Open questions

1. **Smoke-test the Anthropic endpoint with a real key.** Check four things: a multi-turn tool loop with `tool_result`, streaming, prompt caching, and whether Anthropic's own model name (`claude-sonnet-5-5`) is accepted. Runware states these work but shows only a single-turn example.
2. **Beta features.** Are `anthropic-beta` headers and beta-only features passed through, for example structured outputs if they still need a beta header?
3. **Cost visibility.** Does the Anthropic endpoint report Runware cost in the response? It is not documented. If it doesn't, cost tracking would rely on the dashboard or on `getUsageActivity`.
4. **Retry behaviour.** Do 429/503 responses from `/v1/messages` use Anthropic's error shape, so the SDK's built-in retries handle them, or Runware's?
5. **Privacy.** Claude traffic is not covered by ZDR. Is that acceptable for household data? It is probably fine, since meal preferences are low-sensitivity.

## Sources

- [Compatible APIs]: https://runware.ai/docs/tools/compatible-apis (Markdown: `.md` suffix)
- [Models API intro]: https://runware.ai/docs/models-api/introduction
- [Streaming]: https://runware.ai/docs/models-api/streaming
- [Rate Limits]: https://runware.ai/docs/models-api/rate-limits
- [Pricing]: https://runware.ai/docs/models-api/pricing
- [ZDR]: https://runware.ai/docs/models-api/zero-data-retention
- Docs bundle for all of the above: https://runware.ai/docs/llms.txt
- [Model schemas]: https://runware.ai/docs/models/index.json and `https://runware.ai/docs/models/<id>/schema.json`. Read for anthropic-claude-{fable-5, haiku-4-5, opus-4-8, sonnet-4-6}, google-gemini-{3-1-pro, 3-5-flash, 3-flash}, google-gemma-4-31b, minimax-{m2-7, m3}, openai-gpt-{5-4-mini, 5-5}, xai-grok-4-3, zai-glm-5-1
- [Sonnet 4.6 schema]: https://runware.ai/docs/models/anthropic-claude-sonnet-4-6/schema.json
- [MiniMax M3 examples.json]: https://runware.ai/docs/models/minimax-m3/examples.json (example `forced-utc-time-function-call`)
- [Pricing page]: https://runware.ai/pricing (embedded model data with `pricingRates`)
- Sonnet 5.5 model page: https://runware.ai/models/anthropic-claude-sonnet-5-5
- LLM API landing page: https://runware.ai/llm-api
- [Python SDK docs]: https://runware.ai/docs/tools/python and https://runware.ai/docs/tools/python/models
- [PyPI]: https://pypi.org/project/runware-sdk/ and https://pypi.org/project/runware/
