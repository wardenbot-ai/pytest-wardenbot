# Add your chatbot

`pytest-wardenbot` runs tests against any object that satisfies the
`ChatbotAdapter` Protocol. For most chatbots, the bundled `HTTPChatbotAdapter`
is enough. Vendor text APIs and LangChain runnables also have bundled
adapters. For application-specific flows, write a small adapter class.

## The Protocol

A chatbot adapter has three things:

```python
from typing import Protocol
from pytest_wardenbot.adapters.base import ChatbotResponse

class ChatbotAdapter(Protocol):
    name: str
    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse: ...
    def reset_session(self, session_id: str) -> None: ...
```

That's it. Any class with those three attributes works. No registration,
no base-class inheritance, no decorator.

## Path 1: HTTP chatbot (bundled adapter)

Most internal chatbot APIs are JSON over HTTP. Use the bundled adapter:

```python
import os
import pytest
from pytest_wardenbot.adapters.http import HTTPChatbotAdapter

@pytest.fixture
def chatbot():
    return HTTPChatbotAdapter(
        url=os.environ["CHATBOT_URL"],
        headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
        request_field="message",       # the key in the request body that holds the prompt
        response_field="response",     # the key in the response body that holds the text
    )
```

For non-standard response shapes, pass a callable to `response_field`:

```python
HTTPChatbotAdapter(
    url=...,
    response_field=lambda data: data["choices"][0]["message"]["content"],
)
```

## Path 2: bundled vendor adapters or custom application flow

For OpenAI Responses text, install the `[openai]` extra and use the bundled
adapter. It keeps local history per session and sends your system prompt as
Responses instructions:

```python
import pytest
from pytest_wardenbot.adapters.openai_responses import OpenAIResponsesAdapter


@pytest.fixture
def chatbot():
    adapter = OpenAIResponsesAdapter(
        model="gpt-4o-mini",
        system_prompt="You are Example Corp's support assistant. Stay within company policy.",
    )
    try:
        yield adapter
    finally:
        adapter.close()
```

Set `OPENAI_API_KEY` before running this fixture. The adapter always sends `store=False` and does not force sampling parameters. Reset clears local history.
For async calls, use `AsyncOpenAIResponsesAdapter`; the sync shipped suite can
consume it through the adapter bridge described in
[parallel async probes](parallel-async.md).

The bundled Chat Completions and Anthropic Messages adapters remain available
for applications using those APIs. For a LangChain Runnable or LangGraph, see
[the stateful graph recipe](langgraph-state.md). Check
[dependency support](dependency-support.md) for validated SDK combinations.

OpenAI retired the public Assistants API on 26 August 2026. Its adapter class
names remain importable for injected legacy-compatible clients, but their
default constructors fail. [OpenAI migration](migrate-openai.md) explains how
to move text flows and what happens to history and identifiers.

If your chatbot has RAG, authentication, middleware, or a tool loop, wrap its
complete application entry point in a custom `ChatbotAdapter`. Calling a model
directly bypasses those parts of your application. The pattern in
[`examples/custom_openai_adapter/`](https://github.com/wardenbot-ai/pytest-wardenbot/tree/main/examples/custom_openai_adapter)
can be adapted to other vendors or platforms. Bundled text adapters do not
execute your agent's tools.

## Path 3: stateful / multi-turn chatbots

If your bot maintains conversation state, keep a dict keyed by `session_id`
inside the adapter:

```python
class StatefulAdapter:
    name = "stateful"
    stateful = True  # tells the multi-turn test this adapter maintains context

    def __init__(self):
        self._histories: dict[str, list[dict]] = {}

    def send_message(self, prompt, *, session_id=None):
        history = self._histories.setdefault(session_id, []) if session_id is not None else []
        history.append({"role": "user", "content": prompt})
        response_text = call_my_bot(history)
        history.append({"role": "assistant", "content": response_text})
        return ChatbotResponse(text=response_text, raw={"history_len": len(history)})

    def reset_session(self, session_id):
        self._histories.pop(session_id, None)
```

The shipped suite includes a multi-turn jailbreak test
(`test_resists_multi_turn_jailbreak`) that sends priming turns and a payload
under one `session_id`. It only carries real signal against a session-aware
backend like this one: the adapter forwards `session_id` but doesn't replay
prior turns itself, so a stateless endpoint (or the default
`HTTPChatbotAdapter` against a stateless API) treats each turn as fresh and the
test passes trivially.

To make that honest, the test emits a `UserWarning` unless your adapter
declares `stateful = True` (as above). Set it once your endpoint maintains
conversation state — on the bundled HTTP adapter,
`HTTPChatbotAdapter(..., stateful=True)`. The bundled OpenAI and Anthropic
adapters already declare it.

## What gets returned

`ChatbotResponse` is a Pydantic model with three fields:

| Field | Type | Required | What it's for |
|---|---|---|---|
| `text` | `str` | yes | The chatbot's text response. The grading helpers read from here. |
| `raw` | `dict \| None` | optional | The raw API response. Useful for debugging failures. |
| `latency_ms` | `float \| None` | optional | Wall-clock latency of the call. Future tests may use this. |
