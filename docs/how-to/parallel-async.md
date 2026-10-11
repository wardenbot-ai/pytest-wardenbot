# Run probes in parallel (async)

The shipped tests send one prompt per test and run serially. That's fine for a
small suite, but the serial round-trips dominate wall-clock time as your corpus
grows. If your chatbot is behind an async API, fan the probes out concurrently
with `run_probes`.

## Requirements

```bash
pip install "pytest-wardenbot[async]"   # pytest-asyncio
```

You need an `AsyncChatbotAdapter` — the bundled `AsyncHTTPChatbotAdapter`,
`AsyncOpenAIResponsesAdapter`, `AsyncOpenAIChatAdapter`, `AsyncAnthropicMessagesAdapter`,
`AsyncLangChainAdapter`, or your own class with an async `send_message`.

## The recipe

`run_probes` sends a whole corpus concurrently (bounded by `concurrency`) and
returns per-prompt results **in input order**. Grade each result with the same
deterministic helpers the sync tests use:

```python
import pytest

from pytest_wardenbot.adapters.openai_chat import AsyncOpenAIChatAdapter
from pytest_wardenbot.corpus import JAILBREAK_PROMPTS
from pytest_wardenbot.grading.deterministic import assert_no_jailbreak_compliance
from pytest_wardenbot.runners import run_probes


@pytest.fixture
def async_chatbot():
    return AsyncOpenAIChatAdapter(model="gpt-4o-mini", system_prompt="...")


@pytest.mark.asyncio
async def test_jailbreaks_in_parallel(async_chatbot):
    # JAILBREAK_PROMPTS is (prompt, attack_id) — pass it straight through.
    results = await run_probes(async_chatbot, JAILBREAK_PROMPTS, concurrency=5)

    unreachable = [r.attack_id for r in results if not r.ok]
    assert not unreachable, f"bot unreachable for: {unreachable}"

    failures = []
    for r in results:
        try:
            assert_no_jailbreak_compliance(r.response.text, r.prompt)
        except AssertionError as exc:
            failures.append(f"{r.attack_id}: {exc}")
    assert not failures, "\n\n".join(failures)
```

For corpora with a wider shape — encoded-payload and indirect-injection are
`(prompt, trigger_words, attack_id)` — pass `[(p, aid) for p, _, aid in CORPUS]`.
Multi-turn attacks are sequential (priming, then payload), not a single-send
fan-out; use the sync `test_resists_multi_turn_jailbreak` for those.

## Tuning concurrency

`concurrency` (default 5) caps how many sends are in flight at once — raise it
for throughput, lower it to stay under your bot's rate limit. A
`WardenBotInfraError` on one probe (unreachable / malformed bot) is captured in
that result's `.error` (and `.ok` is `False`) instead of sinking the batch, so
you can report every unreachable probe at once. Real bugs (non-infra
exceptions) propagate.


## Use an async adapter from sync tests

A sync `chatbot` fixture can drive an async adapter on one persistent loop:

```python
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.openai_responses import AsyncOpenAIResponsesAdapter


@pytest.fixture
def chatbot():
    with to_sync(AsyncOpenAIResponsesAdapter(model="gpt-4o-mini")) as adapter:
        yield adapter
```

Create, send, reset, and close each bridge on one thread. Do not call it inside
an already running event loop; await the async adapter directly there. Do not
move an adapter previously used on another loop into a bridge. Close is
idempotent and invokes the adapter's public `aclose()` hook on the owned loop,
then closes the loop even if the hook raises. Injected clients remain subject
to the adapter's ownership policy; no private SDK client is inspected. Adapters
without an `aclose()` hook retain responsibility for their other resources.
