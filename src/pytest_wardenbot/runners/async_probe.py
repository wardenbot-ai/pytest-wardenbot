"""Bounded, isolated async chatbot probes with ordered outcomes."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.base import AsyncChatbotAdapter, ChatbotResponse
from pytest_wardenbot.agents.budget import (
    BudgetExceeded,
    CampaignLimits,
    ExecutionBudget,
    RateLimitError,
    RetryPolicy,
    TrialContext,
)
from pytest_wardenbot.agents.contracts import ReasonCode


class ProbeOutcome(StrEnum):
    """Execution outcomes, independent of any security grading."""

    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    BUDGET_EXCEEDED = "budget_exceeded"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class ProbeResult:
    """One requested probe; missing execution never implies a passed check."""

    attack_id: str
    prompt: str
    response: ChatbotResponse | None
    error: WardenBotInfraError | None
    outcome: ProbeOutcome = ProbeOutcome.COMPLETED
    session_id: str | None = None
    attempts: int = 0
    usage: dict[str, int | float] | None = None

    @property
    def ok(self) -> bool:
        """Whether a completed response is available to grade."""
        return (
            self.outcome == ProbeOutcome.COMPLETED
            and self.response is not None
            and self.error is None
        )


async def _drain(tasks: Sequence[asyncio.Task[object]]) -> None:
    """Finish owned tasks even if the caller receives another cancellation."""
    waiter = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while not waiter.done():
        try:
            await asyncio.shield(waiter)
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError


async def _reset(adapter: AsyncChatbotAdapter, session_id: str, cleanup_seconds: float) -> None:
    # Keep cleanup owned and bounded, including during external cancellation.
    task = asyncio.create_task(asyncio.wait_for(adapter.reset_session(session_id), cleanup_seconds))
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    try:
        task.result()
    except TimeoutError:
        raise WardenBotInfraError("Probe session reset timed out") from None
    if cancelled:
        raise asyncio.CancelledError


async def run_probes(
    adapter: AsyncChatbotAdapter,
    prompts: Sequence[tuple[str, str]],
    *,
    concurrency: int | None = None,
    limits: CampaignLimits | None = None,
    retry: RetryPolicy | None = None,
    timeout_seconds: float | None = None,
) -> list[ProbeResult]:
    """Run isolated single-turn probes and return every request in input order.

    ``limits`` bounds the entire batch, including retry attempts. By default the
    batch allows one send per input, runs at concurrency 5, and has a 300 second
    deadline. ``timeout_seconds`` optionally bounds each send including its
    retry waits. Session resets have a separate bounded cleanup allowance.

    Each send receives a unique session ID, reset before and after execution.
    Custom adapters must implement the public async ``reset_session`` protocol
    (stateless adapters can use a no-op). Results describe execution, not safety.
    Infra errors are captured; bugs and external cancellation propagate only
    after siblings have been cancelled and drained. No whole-probe replay occurs.
    Retry is disabled unless explicitly declared safe with ``RetryPolicy``.
    """
    effective_concurrency = (
        concurrency if concurrency is not None else (limits.concurrency if limits else 5)
    )
    if (
        isinstance(effective_concurrency, bool)
        or not isinstance(effective_concurrency, int)
        or effective_concurrency < 1
    ):
        raise ValueError("concurrency must be >= 1 and an integer")
    if timeout_seconds is not None and (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int | float)
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite")
    if retry is not None and retry.max_retries and retry.side_effecting:
        raise ValueError(
            "Probe adapters cannot transmit idempotency keys; write retries are unsupported"
        )
    limits = limits or CampaignLimits(
        max_calls=max(1, len(prompts)),
        max_turns=max(1, len(prompts)),
        concurrency=effective_concurrency,
    )
    budget = ExecutionBudget(limits)
    semaphore = asyncio.Semaphore(effective_concurrency)
    results = [
        ProbeResult(aid, prompt, None, None, ProbeOutcome.NOT_RUN, f"probe-{uuid4().hex}")
        for prompt, aid in prompts
    ]
    started: set[int] = set()

    async def _probe(index: int) -> None:
        result = results[index]
        session_id = result.session_id
        assert session_id is not None
        attempts = 0
        async with semaphore:
            if budget.remaining_seconds <= 0:
                return
            started.add(index)
            context = TrialContext(session_id, budget)
            try:
                context.turn()
                await asyncio.wait_for(
                    adapter.reset_session(session_id),
                    min(limits.cleanup_timeout_seconds, budget.remaining_seconds),
                )

                async def send() -> ChatbotResponse:
                    nonlocal attempts
                    attempts += 1
                    return await adapter.send_message(result.prompt, session_id=session_id)

                call = context.call(send, retry=retry)
                response = await asyncio.wait_for(
                    call,
                    min(timeout_seconds or budget.remaining_seconds, budget.remaining_seconds),
                )
                supplied = response.raw.get("usage") if response.raw is not None else None
                if isinstance(supplied, dict):
                    # Retain only actual supplied numeric fields; nested/unknown fields
                    # are not estimates and are not replaced with fabricated zeros.
                    usage = {
                        key: value
                        for key, value in supplied.items()
                        if key
                        in {
                            "input_tokens",
                            "output_tokens",
                            "total_tokens",
                            "prompt_tokens",
                            "completion_tokens",
                            "estimated_cost_usd",
                        }
                        and not isinstance(value, bool)
                        and isinstance(value, int | float)
                        and (isinstance(value, int) or math.isfinite(value))
                        and value >= 0
                    }
                    context.record_usage(usage)
                result = replace(
                    result,
                    response=response,
                    outcome=ProbeOutcome.COMPLETED,
                    usage=dict(context.usage) if context.usage else None,
                )
            except BudgetExceeded as exc:
                outcome = (
                    ProbeOutcome.TIMEOUT
                    if exc.reason == ReasonCode.CAMPAIGN_DEADLINE
                    else ProbeOutcome.BUDGET_EXCEEDED
                )
                result = replace(result, outcome=outcome)
            except TimeoutError:
                result = replace(result, outcome=ProbeOutcome.TIMEOUT)
            except RateLimitError:
                result = replace(
                    result,
                    error=WardenBotInfraError("Probe rate limit"),
                    outcome=ProbeOutcome.ERROR,
                )
            except WardenBotInfraError as exc:
                result = replace(result, error=exc, outcome=ProbeOutcome.ERROR)
            except asyncio.CancelledError:
                result = replace(result, outcome=ProbeOutcome.CANCELLED)
                current = asyncio.current_task()
                if current is not None and current.cancelling():
                    raise
            finally:
                try:
                    await _reset(adapter, session_id, limits.cleanup_timeout_seconds)
                except WardenBotInfraError as exc:
                    result = replace(result, error=exc, outcome=ProbeOutcome.ERROR)
                finally:
                    results[index] = replace(result, attempts=attempts)

    tasks = [asyncio.create_task(_probe(index)) for index in range(len(results))]
    try:
        # gather propagates bugs immediately; the enclosing finally owns siblings.
        batch = asyncio.gather(*tasks)
        try:
            await asyncio.wait_for(asyncio.shield(batch), budget.remaining_seconds)
        except TimeoutError:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await _drain(tasks)
            for task in tasks:
                if not task.cancelled() and (bug := task.exception()) is not None:
                    raise bug from None
            for index, result in enumerate(results):
                if result.outcome == ProbeOutcome.CANCELLED:
                    results[index] = replace(result, outcome=ProbeOutcome.TIMEOUT)
                elif index not in started:
                    results[index] = replace(result, outcome=ProbeOutcome.NOT_RUN)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        try:
            await _drain(tasks)
        finally:
            # Retrieve gather's eventual exception after all owned workers finish.
            if batch.done():
                with suppress(asyncio.CancelledError):
                    batch.exception()
    return results
