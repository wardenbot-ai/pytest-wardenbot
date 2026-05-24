# Example: Anthropic Messages

Uses the bundled `AnthropicMessagesAdapter` against the Anthropic Messages
API. This is the fastest path when your chatbot IS an Anthropic model
(Claude) with a system prompt.

## Run

```bash
pip install "pytest-wardenbot[anthropic]"
export ANTHROPIC_API_KEY=sk-ant-...
pytest -v
```

## What this shows

- Driving the shipped wardenbot tests against a Claude model via the bundled
  adapter — no custom class to write.
- Anthropic's API distinguishes the `system` prompt (a top-level argument)
  from the `messages` list (user/assistant turns only). The adapter handles
  this naturally; you pass `system_prompt=` to the constructor.
- Multi-turn session support is built into the adapter (`session_id` /
  `reset_session`); the shipped v0.1 tests are single-turn so this example
  doesn't exercise it, but it's available for your own tests.

## Async variant

`AsyncAnthropicMessagesAdapter` is the async sibling. The shipped v0.1
tests are synchronous, so pass it through `to_sync(...)` to use it from the
default `chatbot` fixture:

```python
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.anthropic_msgs import AsyncAnthropicMessagesAdapter

@pytest.fixture
def chatbot():
    return to_sync(AsyncAnthropicMessagesAdapter(model="claude-haiku-4-5"))
```
