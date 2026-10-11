# Migrate OpenAI text adapters

OpenAI retired the public Assistants API on **26 August 2026** and reports that
it is unavailable. Move current integrations to Responses. The official
[Assistants migration guide](https://developers.openai.com/api/docs/assistants/migration)
explains the replacement API and using conversation messages retained by your
application; old thread message retrieval is no longer available.

## Use the Responses text adapter

Install `pytest-wardenbot[openai]` and set `OPENAI_API_KEY`. Replace a default
Assistants fixture with your model and instructions:

```python
import pytest
from pytest_wardenbot.adapters.openai_responses import OpenAIResponsesAdapter


@pytest.fixture
def chatbot():
    adapter = OpenAIResponsesAdapter(
        model="gpt-4o-mini",
        system_prompt="You are Example Corp's support assistant. Follow company policy.",
    )
    try:
        yield adapter
    finally:
        adapter.close()
```

The async counterpart is `AsyncOpenAIResponsesAdapter` in the same module.
For sync tests around the async adapter, use a persistent bridge and yield it
from a fixture:

```python
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.openai_responses import AsyncOpenAIResponsesAdapter


@pytest.fixture
def chatbot():
    with to_sync(AsyncOpenAIResponsesAdapter(model="gpt-4o-mini")) as adapter:
        yield adapter
```

The bridge must stay on its creating thread, outside running event loops, and
an adapter already used on another loop must not be moved into it.
Its context manager calls the adapter's public async cleanup on that same loop.
Use `close()` / `await aclose()` to release internally created clients after
use; injected clients remain the caller's responsibility. Both adapters return
`ChatbotResponse` and retain the standard `send_message` /
`reset_session` interfaces. The adapter sends `system_prompt` as Responses
instructions, does not force temperature, and extracts assistant text rather
than serializing arbitrary response objects. See the
[API reference](../reference/api.md) and
[dependency support](dependency-support.md) for available adapters and tested
SDK versions.

## History and identifiers

The Responses adapter keeps history **in the local adapter instance**, keyed by
WardenBot's `session_id`. A call without a session ID is a one-shot request.
Repeated calls with one ID replay that conversation's local input/output items.
The adapter always sends `store=False`; this selects response storage
behavior, rather than guaranteeing anything about all provider data retention.
OpenAI describes [Responses state options](https://developers.openai.com/api/docs/guides/migrate-to-responses)
separately, including server-managed conversations.

`reset_session(session_id)` clears local history for that ID. It does not
delete a legacy remote Assistants thread, delete a Responses conversation, or
recover remote history. History cleanup or migration outside this adapter is
your application's responsibility.

An old `assistant_id` such as `asst_...` is not a Responses model, prompt, or
conversation ID. A legacy `thread_id` is not a Responses conversation ID.
Transfer your application instructions and any history you already retained;
do not pass legacy identifiers into unrelated Responses fields. This adapter's
session IDs are local keys, so choose fresh probe IDs independently of remote
objects.

## Legacy compatibility

`OpenAIAssistantsAdapter` and `AsyncOpenAIAssistantsAdapter` remain importable.
Calling either without `client=` raises `WardenBotInfraError` with migration
instructions before importing the OpenAI SDK or making a request.

An explicitly injected test client or compatible proxy can retain the legacy
`beta.threads` contract: thread create/delete, message create/list, and run
create/retrieve. Construction validates those methods and emits a
`DeprecationWarning` that the public service has retired. An ordinary current
OpenAI SDK client does not make the retired public endpoint available. This
seam preserves existing fixtures and compatible private services; it is not
an operational public Assistants integration. Legacy thread deletion remains
best-effort and should not be used as proof of remote data removal.

## Agents and tools

The bundled Responses adapter handles completed text replies. It does not
execute function calls, tool outputs, or an agent tool loop. A workflow that
requests tools instead of a completed assistant text reply is an infrastructure
error for this adapter. To test a full agent today, wrap your application's
completed agent flow in a custom adapter or use its deployed HTTP endpoint.
Dedicated agent-flow adapters and tool side-effect assertions remain separate
future work.

For stateful LangGraph applications, use the
[graph recipe](langgraph-state.md), which maps messages state and resets the
checkpointer under independent thread IDs.
