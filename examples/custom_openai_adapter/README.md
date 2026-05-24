# Example: custom OpenAI Chat adapter

How to write your own `ChatbotAdapter` for any vendor SDK. This example uses
the OpenAI Python SDK against the Chat Completions endpoint, but the same
pattern applies to Anthropic, LangChain, MCP, or anything else with a Python
client.

> A built-in `OpenAIChatAdapter` lands in v0.2 of pytest-wardenbot. Until then,
> this is the recipe.

## Run

```bash
pip install pytest-wardenbot openai
export OPENAI_API_KEY=sk-...
pytest -v
```

## What this shows

1. **A minimal adapter class** that satisfies the `ChatbotAdapter` Protocol.
   It needs three things: a `name` attribute, a `send_message` method, and a
   `reset_session` method (no-op for stateless endpoints).

2. **Wrapping a sync SDK call** in the adapter. Async SDKs work the same way
   with `asyncio.run(...)` inside `send_message`.

3. **A custom system prompt** that frames the bot for testing. Without it, a
   bare-model chat is hard to score — every chatbot in production has a system
   prompt; the tests should run against your real one.

## Customize for your stack

- Swap `openai` for `anthropic`, `langchain`, or your favorite SDK.
- Replace `SYSTEM_PROMPT` with your real production system prompt.
- For agents/tools, capture the tool calls and add them to `ChatbotResponse.raw`
  so future tests can inspect them.
