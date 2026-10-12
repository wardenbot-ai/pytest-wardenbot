"""Tests for the parallel async probe runner.

Uses an in-memory async stub adapter — no real API, no network.
"""

from __future__ import annotations

import asyncio

import pytest

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.base import ChatbotResponse
from pytest_wardenbot.runners.async_probe import ProbeResult, run_probes

_PROMPTS = tuple((f"prompt {i}", f"attack-{i}") for i in range(10))


class _ConcurrencyTrackingAdapter:
    """Records the peak number of in-flight sends, to verify the semaphore cap."""

    name = "concurrency-tracking"
    stateful = False

    def __init__(self, delay: float = 0.02) -> None:
        self._delay = delay
        self._in_flight = 0
        self.peak_in_flight = 0

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self._delay)
            return ChatbotResponse(text=f"reply to {prompt}")
        finally:
            self._in_flight -= 1

    async def reset_session(self, session_id: str) -> None:
        del session_id


class _FlakyAdapter:
    """Raises WardenBotInfraError for one specific prompt; succeeds otherwise."""

    name = "flaky"
    stateful = False

    def __init__(self, fail_prompt: str) -> None:
        self._fail_prompt = fail_prompt

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        if prompt == self._fail_prompt:
            raise WardenBotInfraError("bot unreachable")
        return ChatbotResponse(text=f"reply to {prompt}")

    async def reset_session(self, session_id: str) -> None:
        del session_id


class _BuggyAdapter:
    """Raises a non-infra exception — should propagate, not be captured."""

    name = "buggy"
    stateful = False

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del prompt, session_id
        raise ValueError("a real bug, not an infra error")

    async def reset_session(self, session_id: str) -> None:
        del session_id


@pytest.mark.asyncio
async def test_returns_results_in_input_order() -> None:
    adapter = _ConcurrencyTrackingAdapter()
    results = await run_probes(adapter, _PROMPTS, concurrency=4)
    assert [r.attack_id for r in results] == [aid for _, aid in _PROMPTS]
    assert [r.prompt for r in results] == [p for p, _ in _PROMPTS]
    assert all(r.ok and r.response is not None for r in results)
    assert results[3].response is not None
    assert results[3].response.text == "reply to prompt 3"


@pytest.mark.asyncio
async def test_respects_concurrency_cap() -> None:
    adapter = _ConcurrencyTrackingAdapter()
    await run_probes(adapter, _PROMPTS, concurrency=3)
    assert adapter.peak_in_flight <= 3
    # And it actually ran concurrently (not effectively serial).
    assert adapter.peak_in_flight > 1


@pytest.mark.asyncio
async def test_concurrency_one_is_serial() -> None:
    adapter = _ConcurrencyTrackingAdapter()
    await run_probes(adapter, _PROMPTS, concurrency=1)
    assert adapter.peak_in_flight == 1


@pytest.mark.asyncio
async def test_captures_infra_error_without_sinking_batch() -> None:
    results = await run_probes(_FlakyAdapter(fail_prompt="prompt 5"), _PROMPTS, concurrency=4)
    assert len(results) == len(_PROMPTS)
    failed = [r for r in results if not r.ok]
    assert len(failed) == 1
    assert failed[0].prompt == "prompt 5"
    assert failed[0].response is None
    assert isinstance(failed[0].error, WardenBotInfraError)
    # Every other probe still produced a response.
    assert all(r.ok for r in results if r.prompt != "prompt 5")


@pytest.mark.asyncio
async def test_non_infra_exception_propagates() -> None:
    with pytest.raises(ValueError, match="a real bug"):
        await run_probes(_BuggyAdapter(), _PROMPTS, concurrency=4)


@pytest.mark.asyncio
async def test_empty_prompts_returns_empty() -> None:
    assert await run_probes(_ConcurrencyTrackingAdapter(), [], concurrency=4) == []


@pytest.mark.asyncio
async def test_concurrency_below_one_raises() -> None:
    with pytest.raises(ValueError, match="concurrency must be >= 1"):
        await run_probes(_ConcurrencyTrackingAdapter(), _PROMPTS, concurrency=0)


def test_probe_result_ok_property() -> None:
    ok = ProbeResult(attack_id="a", prompt="p", response=ChatbotResponse(text="x"), error=None)
    bad = ProbeResult(attack_id="a", prompt="p", response=None, error=WardenBotInfraError("x"))
    assert ok.ok is True
    assert bad.ok is False


class _SessionAdapter:
    name = "session-isolation"
    stateful = True

    def __init__(self) -> None:
        self.sessions: dict[str, list[str]] = {}
        self.seen: list[str] = []
        self.resets: list[str] = []
        self.active = 0
        self.finished = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def reset_session(self, session_id: str) -> None:
        self.resets.append(session_id)
        self.sessions.pop(session_id, None)

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        assert session_id is not None
        self.seen.append(session_id)
        history = self.sessions.setdefault(session_id, [])
        assert history == []
        history.append(prompt)
        self.active += 1
        self.started.set()
        try:
            await self.release.wait()
            return ChatbotResponse(text=prompt)
        finally:
            self.active -= 1
            self.finished += 1


@pytest.mark.asyncio
async def test_concurrent_batches_use_unique_reset_sessions() -> None:
    adapter = _SessionAdapter()
    adapter.release.set()
    batches = await asyncio.gather(run_probes(adapter, _PROMPTS), run_probes(adapter, _PROMPTS))
    assert len(set(adapter.seen)) == 20
    assert adapter.sessions == {}
    assert all(adapter.resets.count(session) == 2 for session in adapter.seen)
    assert all(result.session_id in adapter.seen for batch in batches for result in batch)


@pytest.mark.asyncio
async def test_global_call_cap_under_racing_workers() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits
    from pytest_wardenbot.runners.async_probe import ProbeOutcome

    adapter = _SessionAdapter()
    adapter.release.set()
    results = await run_probes(
        adapter, _PROMPTS, limits=CampaignLimits(max_calls=3, concurrency=10)
    )
    assert len(adapter.seen) == 3
    assert sum(result.attempts for result in results) == 3
    assert sum(result.ok for result in results) == 3
    assert len(results) == 10
    assert all(result.outcome == ProbeOutcome.BUDGET_EXCEEDED for result in results[3:])
    assert adapter.sessions == {}


@pytest.mark.asyncio
async def test_deadline_drains_sends_and_keeps_queued_denominator() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits
    from pytest_wardenbot.runners.async_probe import ProbeOutcome

    adapter = _SessionAdapter()
    results = await run_probes(
        adapter,
        _PROMPTS,
        limits=CampaignLimits(timeout_seconds=0.03, concurrency=2),
    )
    assert adapter.active == 0
    assert adapter.finished == 2
    assert adapter.sessions == {}
    assert [result.outcome for result in results[:2]] == [ProbeOutcome.TIMEOUT] * 2
    assert all(result.outcome == ProbeOutcome.NOT_RUN for result in results[2:])
    assert not any(result.ok for result in results)


@pytest.mark.asyncio
async def test_external_cancellation_drains_and_resets() -> None:
    adapter = _SessionAdapter()
    task = asyncio.create_task(run_probes(adapter, _PROMPTS, concurrency=3))
    await adapter.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter.active == 0
    assert adapter.sessions == {}
    finished = adapter.finished
    await asyncio.sleep(0)
    assert adapter.finished == finished


@pytest.mark.asyncio
async def test_unexpected_bug_cancels_and_drains_sibling() -> None:
    class BugWithSibling(_SessionAdapter):
        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            if prompt == "bug":
                await self.started.wait()
                raise ValueError("probe bug")
            return await super().send_message(prompt, session_id=session_id)

    adapter = BugWithSibling()
    with pytest.raises(ValueError, match="probe bug"):
        await run_probes(adapter, [("blocked", "a"), ("bug", "b")], concurrency=2)
    assert adapter.active == 0
    assert adapter.sessions == {}
    assert adapter.finished == 1


@pytest.mark.asyncio
async def test_per_probe_timeout_and_self_cancel_are_not_ok() -> None:
    from pytest_wardenbot.runners.async_probe import ProbeOutcome

    adapter = _SessionAdapter()
    results = await run_probes(adapter, [("blocked", "a")], timeout_seconds=0.01)
    assert results[0].outcome == ProbeOutcome.TIMEOUT
    assert not results[0].ok
    assert adapter.active == 0

    class SelfCancel(_ConcurrencyTrackingAdapter):
        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            raise asyncio.CancelledError

    result = (await run_probes(SelfCancel(), [("p", "a")]))[0]
    assert result.outcome == ProbeOutcome.CANCELLED
    assert not result.ok


@pytest.mark.asyncio
async def test_rate_limit_is_not_retried_without_explicit_safety() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits, RateLimitError, RetryPolicy

    class RateLimited(_ConcurrencyTrackingAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            self.calls += 1
            if self.calls == 1:
                raise RateLimitError()
            return ChatbotResponse(text="ok")

    adapter = RateLimited()
    result = (await run_probes(adapter, [("p", "a")]))[0]
    assert not result.ok
    assert adapter.calls == 1
    adapter = RateLimited()
    result = (
        await run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(max_calls=2),
            retry=RetryPolicy(max_retries=1, safe_to_retry=True),
        )
    )[0]
    assert result.ok
    assert result.attempts == 2
    assert adapter.calls == 2
    with pytest.raises(ValueError, match="write retries"):
        await run_probes(
            adapter,
            [("p", "a")],
            retry=RetryPolicy(
                max_retries=1,
                safe_to_retry=True,
                side_effecting=True,
                idempotent=True,
                idempotency_key="stable",
            ),
        )
    assert adapter.calls == 2


@pytest.mark.asyncio
async def test_only_supplied_numeric_usage_is_retained() -> None:
    class UsageAdapter(_ConcurrencyTrackingAdapter):
        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            return ChatbotResponse(
                text="ok",
                raw={
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 2,
                        "unknown": None,
                        "boolean": True,
                        "nested": {"tokens": 5},
                    }
                },
            )

    result = (await run_probes(UsageAdapter(), [("p", "a")]))[0]
    assert result.usage == {"input_tokens": 7, "output_tokens": 2}
    assert (await run_probes(_ConcurrencyTrackingAdapter(), [("p", "a")]))[0].usage is None


@pytest.mark.asyncio
async def test_cleanup_timeout_is_infra_error_and_drained() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits

    class SlowReset(_ConcurrencyTrackingAdapter):
        def __init__(self) -> None:
            super().__init__(delay=0)
            self.resets = 0
            self.active_reset = 0

        async def reset_session(self, session_id: str) -> None:
            self.resets += 1
            if self.resets > 1:
                self.active_reset += 1
                try:
                    await asyncio.Event().wait()
                finally:
                    self.active_reset -= 1

    adapter = SlowReset()
    result = (
        await run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(cleanup_timeout_seconds=0.01),
        )
    )[0]
    assert not result.ok
    assert isinstance(result.error, WardenBotInfraError)
    assert adapter.active_reset == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, 1.5, float("nan")])
async def test_invalid_concurrency_rejected(value: int) -> None:
    with pytest.raises(ValueError, match="concurrency"):
        await run_probes(_ConcurrencyTrackingAdapter(), _PROMPTS, concurrency=value)


def test_missing_response_is_not_ok() -> None:
    assert not ProbeResult("a", "p", None, None).ok


@pytest.mark.asyncio
async def test_retry_consumes_global_budget_without_replaying_send() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits, RateLimitError, RetryPolicy
    from pytest_wardenbot.runners.async_probe import ProbeOutcome

    class Limited(_ConcurrencyTrackingAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            self.calls += 1
            raise RateLimitError()

    adapter = Limited()
    result = (
        await run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(max_calls=1),
            retry=RetryPolicy(max_retries=2, safe_to_retry=True),
        )
    )[0]
    assert result.outcome == ProbeOutcome.BUDGET_EXCEEDED
    assert not result.ok
    assert adapter.calls == result.attempts == 1


@pytest.mark.asyncio
async def test_cancel_during_retry_sleep_drains_cleanup() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits, RateLimitError, RetryPolicy

    class Limited(_SessionAdapter):
        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            assert session_id is not None
            self.seen.append(session_id)
            self.started.set()
            raise RateLimitError(retry_after=60)

    adapter = Limited()
    task = asyncio.create_task(
        run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(max_calls=2),
            retry=RetryPolicy(max_retries=1, safe_to_retry=True),
        )
    )
    await adapter.started.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(adapter.seen) == 1
    assert adapter.resets.count(adapter.seen[0]) == 2


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_orphan_reset() -> None:
    class ControlledReset(_SessionAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_started = asyncio.Event()
            self.cleanup_release = asyncio.Event()

        async def reset_session(self, session_id: str) -> None:
            if session_id in self.seen:
                self.cleanup_started.set()
                await self.cleanup_release.wait()
            await super().reset_session(session_id)

    adapter = ControlledReset()
    task = asyncio.create_task(run_probes(adapter, [("p", "a")]))
    await adapter.started.wait()
    task.cancel()
    await adapter.cleanup_started.wait()
    task.cancel()
    adapter.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter.sessions == {}
    assert adapter.active == 0
    assert adapter.resets.count(adapter.seen[0]) == 2


@pytest.mark.asyncio
async def test_generic_infra_failure_never_duplicates_side_effect() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits, RetryPolicy

    class WritesThenFails(_ConcurrencyTrackingAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.effects = 0

        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            self.effects += 1
            raise WardenBotInfraError("response lost after acceptance")

    adapter = WritesThenFails()
    result = (
        await run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(max_calls=3),
            retry=RetryPolicy(max_retries=2, safe_to_retry=True),
        )
    )[0]
    assert not result.ok
    assert adapter.effects == 1
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_turn_cap_limits_probes_before_sending() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits
    from pytest_wardenbot.runners.async_probe import ProbeOutcome

    adapter = _SessionAdapter()
    adapter.release.set()
    results = await run_probes(adapter, _PROMPTS, limits=CampaignLimits(max_turns=2, concurrency=8))
    assert len(adapter.seen) == 2
    assert sum(result.ok for result in results) == 2
    assert all(result.outcome == ProbeOutcome.BUDGET_EXCEEDED for result in results[2:])


@pytest.mark.asyncio
async def test_external_cancellation_during_failing_cleanup_stays_cancellation() -> None:
    class FailingReset(_SessionAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_started = asyncio.Event()
            self.cleanup_release = asyncio.Event()

        async def reset_session(self, session_id: str) -> None:
            if session_id in self.seen:
                self.cleanup_started.set()
                await self.cleanup_release.wait()
                await super().reset_session(session_id)
                raise RuntimeError("cleanup bug")
            await super().reset_session(session_id)

    adapter = FailingReset()
    adapter.release.set()
    task = asyncio.create_task(run_probes(adapter, [("p", "a")]))
    await adapter.cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    adapter.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert adapter.sessions == {}
    assert adapter.active == 0


@pytest.mark.asyncio
async def test_deadline_does_not_hide_unexpected_cleanup_bug() -> None:
    from pytest_wardenbot.agents.budget import CampaignLimits

    class FailingReset(_SessionAdapter):
        async def reset_session(self, session_id: str) -> None:
            await super().reset_session(session_id)
            if session_id in self.seen:
                raise RuntimeError("cleanup bug")

    adapter = FailingReset()
    with pytest.raises(RuntimeError, match="cleanup bug"):
        await run_probes(
            adapter,
            [("p", "a")],
            limits=CampaignLimits(timeout_seconds=0.01),
        )
    assert adapter.sessions == {}
    assert adapter.active == 0
