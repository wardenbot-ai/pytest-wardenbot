# Example: custom OpenAI Chat adapter (template for any vendor SDK)

How to write your own `ChatbotAdapter` for any vendor SDK. This example uses
the OpenAI Python SDK against the Chat Completions endpoint, but the same
pattern applies to LangChain, MCP, or anything else with a Python client.

> **If your chatbot just IS an OpenAI Chat model**, use the bundled
> `OpenAIChatAdapter` instead — see [`../openai_chat/`](../openai_chat/).
> Same for Anthropic — see [`../anthropic_messages/`](../anthropic_messages/).
> This example is the template for cases where you have middleware between
> the user and the model (RAG, function calling with custom side effects,
> prompt rewriting, etc.) and you want to test the whole pipeline as one bot.

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
