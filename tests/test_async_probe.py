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
