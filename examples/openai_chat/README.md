# Example: OpenAI Chat Completions

Uses the bundled `OpenAIChatAdapter` against the OpenAI Chat Completions API.
This is the fastest path when your chatbot IS an OpenAI model with a system
prompt — no custom adapter code needed.

## Run

```bash
pip install "pytest-wardenbot[openai]"
export OPENAI_API_KEY=sk-...
pytest -v
```

## What this shows

- Driving the shipped wardenbot tests against an OpenAI Chat model via the
  bundled adapter — no custom class to write.
- Configuring the system prompt that frames the bot for testing. Without one,
  a bare-model chat is hard to score; every production chatbot has a system
  prompt, and the tests should run against your real one.
- Multi-turn session support is built into the adapter (`session_id` /
  `reset_session`); the shipped v0.1 tests are single-turn so this example
  doesn't exercise it, but it's available for your own tests.

## When to use this vs. the custom adapter example

- **Use this** if your chatbot calls OpenAI directly (no orchestration layer
  in between) and uses the standard Chat Completions API.
- **Use [`../custom_openai_adapter/`](../custom_openai_adapter/)** as the
  template if your chatbot has middleware between the user and the model
  (RAG, function calling with custom side effects, prompt rewriting, etc.).
  You'll want to test the whole pipeline, not just the OpenAI call.

## Async variant

`AsyncOpenAIChatAdapter` is the async sibling for users who want parallel
fan-out in their own async test suites. The shipped v0.1 tests are
synchronous, so pass it through `to_sync(...)` to use it from the default
`chatbot` fixture:

```python
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.openai_chat import AsyncOpenAIChatAdapter

@pytest.fixture
def chatbot():
    return to_sync(AsyncOpenAIChatAdapter(model="gpt-4o-mini"))
```
