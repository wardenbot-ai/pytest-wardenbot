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
`AsyncLangChainAdapter`, or your own class with async `send_message(prompt, *, session_id=None)` and
`reset_session(session_id)` methods. Stateless custom adapters should implement
`reset_session` as an async no-op. Older lightweight stubs that only implemented
`send_message` need this reset hook to satisfy `AsyncChatbotAdapter`.

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

    incomplete = [(r.attack_id, r.outcome.value) for r in results if not r.ok]
    assert not incomplete, f"probes unavailable for grading: {incomplete}"

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
exceptions) propagate after sibling tasks are cancelled and drained. External
cancellation also propagates after cleanup. Each probe receives a unique session
ID, including across overlapping batches on the same adapter, with reset before
and after execution. The adapter must honor session IDs to isolate state.

## Bound the entire batch

```python
from pytest_wardenbot.agents.budget import CampaignLimits, RetryPolicy

results = await run_probes(
    async_chatbot,
    JAILBREAK_PROMPTS,
    limits=CampaignLimits(
        max_calls=40,             # all instrumented send attempts, including retries
        max_turns=29,             # logical single-turn probes
        concurrency=4,
        timeout_seconds=60,      # overall deadline, including queue and retry waits
        cleanup_timeout_seconds=2,
    ),
    timeout_seconds=10,          # optional per-probe send/retry deadline
)
```

Without explicit limits, the runner permits one send per input, uses concurrency
5, a 300 second batch deadline and a 5 second session-cleanup allowance. An
explicit `concurrency` overrides `limits.concurrency`. These limits count
instrumented adapter attempts; an opaque adapter can make additional model or
tool calls internally. The runner cannot enforce a provider spending cap.

The list always contains one result per requested input, in input order.
`outcome` distinguishes `completed`, `error`, `timeout`, `cancelled`,
`budget_exceeded` and `not_run`. A deadline can leave queued probes `not_run`;
those probes remain in the denominator. `.ok` is true only when a completed
response is available and no infrastructure or cleanup error occurred. It is an
execution check, not a passed security grade. Grade only `.ok` results, and
report unavailable probes separately; never count them as resisted attacks.

Cancellation and deadlines cancel and await owned sends and reset tasks. The
cleanup allowance can extend beyond the batch deadline. Like Python async
cancellation generally, this requires adapters to cooperate with cancellation;
an adapter that suppresses cancellation indefinitely cannot be forcibly stopped
by an in-process runner. A session cleanup timeout becomes an infrastructure
error rather than a gradeable completion.

`attempts` reports actual send attempts. `usage` is `None` when the adapter
supplies no supported counters in `response.raw["usage"]`; otherwise it retains
only supplied numeric `input_tokens`, `output_tokens`, `total_tokens`,
`prompt_tokens`, `completion_tokens` and `estimated_cost_usd` fields. No missing
counter is inferred or replaced with zero. Dollar fields are estimates, not
provider-enforced limits; unavailable failed-attempt usage stays unknown.

## Retry only explicitly safe reads

Retry is off by default because an opaque chatbot send may execute writes.
Adapters can classify a rate limit with `RateLimitError` from
`pytest_wardenbot.agents.budget`. A generic `WardenBotInfraError` is never retried.
For an operation you have established is safe to repeat:

```python
results = await run_probes(
    read_only_chatbot,
    prompts,
    limits=CampaignLimits(max_calls=20, max_turns=10, concurrency=2),
    retry=RetryPolicy(max_retries=1, delay_seconds=0.1, safe_to_retry=True),
)
```

Each retry consumes a call claim before sending and keeps the same isolated
session. A call limit or deadline can prevent a retry. The runner does not replay
whole targets. Probe adapters have no public idempotency-key argument, so
`side_effecting=True` retry policies are rejected even with a key; perform such
operations through a target integration that transmits a stable key to a service
that actually deduplicates writes.


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
