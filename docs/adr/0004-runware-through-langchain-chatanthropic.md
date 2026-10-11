# Runware is reached through LangChain's ChatAnthropic on its Anthropic-format endpoint

Pickled's agent calls Claude on Runware through `langchain-anthropic`'s `ChatAnthropic`, pointed at Runware's Anthropic-compatible `/v1/messages` endpoint. It does not use Runware's OpenAI-compatible endpoint or its native API. Runware documents tool use only for the Anthropic-format endpoint. The native API can't return tool results. Prompt caching and the Anthropic tool format work end to end (verified in "Smoke-test Runware's Anthropic endpoint with a real key"). Only one factory, `make_chat_model(role)`, builds models. It holds everything specific to Runware: the base URL, an `Authorization: Bearer` header passed through `default_headers` (Runware rejects `x-api-key`, which LangChain sends by default), an explicit timeout and the retry count. Switching provider means changing the base URL and key to another Anthropic-format endpoint, such as Anthropic itself. We chose not to support every provider through `init_chat_model`: caching, the tool format and the auth quirk are all specific to the Anthropic format, and nothing needs a second provider.

## Consequences

- Runware checks request bodies against a fixed schema, so Anthropic beta features that add new body fields (such as `context_management`) are unavailable.
- Runware reports token usage but not cost, so spend has to be computed from `usage_metadata` × a price table on our side.
- Claude through Runware has no Zero Data Retention. We accept this for v1 because the data is low-sensitivity (taste notes, Food Goals, meals, household size). Prompts never include personal identifiers.
- Haiku isn't offered on Runware. Chat and drafting each have their own model setting, and both default to Sonnet 5.5.
