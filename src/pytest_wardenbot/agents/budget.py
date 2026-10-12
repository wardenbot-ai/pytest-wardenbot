"""Cooperative, run-wide accounting and explicitly safe rate-limit retries."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TypeVar

from pytest_wardenbot.agents.contracts import ReasonCode, RunResult, _identifier

T = TypeVar("T")


def _positive_integer(value: object, label: str, *, zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise ValueError(f"{label} must be a {'nonnegative' if zero else 'positive'} integer")


def _duration(value: object, label: str, *, zero: bool = False) -> None:
    try:
        finite = isinstance(value, int | float) and math.isfinite(value)
    except OverflowError:
        finite = False
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not finite
        or value < 0
        or (not zero and value == 0)
    ):
        raise ValueError(f"{label} must be a finite {'nonnegative' if zero else 'positive'} number")


@dataclass(frozen=True)
class CampaignLimits:
    max_calls: int = 100
    max_turns: int = 100
    timeout_seconds: float = 300
    cleanup_timeout_seconds: float = 5
    concurrency: int = 1

    def __post_init__(self) -> None:
        for label in ("max_calls", "max_turns", "concurrency"):
            _positive_integer(getattr(self, label), label)
        for label in ("timeout_seconds", "cleanup_timeout_seconds"):
            _duration(getattr(self, label), label)


class BudgetExceeded(Exception):
    """A claim was rejected before the instrumented operation began."""

    def __init__(self, reason: ReasonCode) -> None:
        self.reason = reason
        super().__init__(reason.value)


class ExecutionBudget:
    """One atomic counter set. Integrations must claim before every operation."""

    def __init__(self, limits: CampaignLimits) -> None:
        self.limits = limits
        self._deadline = time.monotonic() + limits.timeout_seconds
        self._calls = 0
        self._turns = 0
        self._lock = threading.Lock()

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    @property
    def turns(self) -> int:
        with self._lock:
            return self._turns

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    def _reason(self) -> ReasonCode | None:
        if self.remaining_seconds <= 0:
            return ReasonCode.CAMPAIGN_DEADLINE
        if self._calls >= self.limits.max_calls:
            return ReasonCode.CALL_BUDGET_EXHAUSTED
        if self._turns >= self.limits.max_turns:
            return ReasonCode.TURN_BUDGET_EXHAUSTED
        return None

    @property
    def stop_reason(self) -> ReasonCode | None:
        with self._lock:
            return self._reason()

    def _claim(self, kind: str) -> None:
        with self._lock:
            # Calls on the last permitted turn must still be possible. Each
            # counter prevents only another operation of its own kind.
            reason = ReasonCode.CAMPAIGN_DEADLINE if self.remaining_seconds <= 0 else None
            if kind == "call" and self._calls >= self.limits.max_calls:
                reason = reason or ReasonCode.CALL_BUDGET_EXHAUSTED
            if kind == "turn" and self._turns >= self.limits.max_turns:
                reason = reason or ReasonCode.TURN_BUDGET_EXHAUSTED
            if reason is not None:
                raise BudgetExceeded(reason)
            if kind == "call":
                self._calls += 1
            else:
                self._turns += 1

    def claim_call(self) -> None:
        self._claim("call")

    def claim_turn(self) -> None:
        self._claim("turn")


@dataclass(frozen=True)
class RetryPolicy:
    """Retries require declared safety; keyed writes require provider deduplication.

    A key is a declaration, not local deduplication. The operation must send the
    same key to a service that honors it. Only RateLimitError is retried.
    """

    max_retries: int = 0
    delay_seconds: float = 0
    safe_to_retry: bool = False
    side_effecting: bool = False
    idempotent: bool = False
    idempotency_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _positive_integer(self.max_retries, "max_retries", zero=True)
        _duration(self.delay_seconds, "delay_seconds", zero=True)
        if not all(
            isinstance(value, bool)
            for value in (self.safe_to_retry, self.side_effecting, self.idempotent)
        ):
            raise ValueError("Retry declarations must be booleans")
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip()
        ):
            raise ValueError("An idempotency key must be a nonempty string")
        if (self.idempotent or self.idempotency_key is not None) and not self.side_effecting:
            raise ValueError("Idempotency declarations require a side-effecting operation")
        if (self.idempotency_key is not None) != self.idempotent:
            raise ValueError("Idempotency requires both its declaration and a stable key")
        if self.max_retries and not self.safe_to_retry:
            raise ValueError("Retries require an explicit safe_to_retry declaration")
        if self.max_retries and self.side_effecting and not self.idempotent:
            raise ValueError("Side-effect retries require idempotency and a stable key")


class RateLimitError(Exception):
    """Integration-classified rate limit, without a provider exception message."""

    def __init__(self, *, retry_after: float | None = None) -> None:
        if retry_after is not None:
            _duration(retry_after, "retry_after", zero=True)
        self.retry_after = retry_after
        super().__init__("Rate limit")


@dataclass
class TrialContext:
    trial_id: str
    budget: ExecutionBudget
    calls: int = field(default=0, init=False)
    turns: int = field(default=0, init=False)
    usage: dict[str, int | float] = field(default_factory=dict, init=False, repr=False)
    result: RunResult | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _identifier(self.trial_id)

    def turn(self) -> None:
        """Claim before starting a turn, including any model or tool work."""
        self.budget.claim_turn()
        self.turns += 1

    def record_usage(self, usage: Mapping[str, int | float]) -> None:
        """Add supplied usage. Unknown usage stays unknown; dollars are estimates."""
        updated = dict(self.usage)
        for key, value in usage.items():
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, int | float)
                or (isinstance(value, float) and not math.isfinite(value))
                or value < 0
            ):
                raise ValueError("Usage must contain finite nonnegative numbers")
            try:
                total = updated.get(key, 0) + value
            except OverflowError:
                raise ValueError("Accumulated usage must remain finite") from None
            if isinstance(total, float) and not math.isfinite(total):
                raise ValueError("Accumulated usage must remain finite")
            updated[key] = total
        self.usage = updated

    async def call(
        self, operation: Callable[..., Awaitable[T]], *, retry: RetryPolicy | None = None
    ) -> T:
        """Claim every attempt and retry only explicitly classified rate limits."""
        policy = retry or RetryPolicy()
        for attempt in range(policy.max_retries + 1):
            self.budget.claim_call()
            self.calls += 1
            try:
                if policy.side_effecting and policy.idempotent:
                    return await operation(idempotency_key=policy.idempotency_key)
                return await operation()
            except RateLimitError as exc:
                if attempt >= policy.max_retries:
                    raise
                delay = max(policy.delay_seconds, exc.retry_after or 0)
                if delay >= self.budget.remaining_seconds:
                    raise BudgetExceeded(ReasonCode.CAMPAIGN_DEADLINE) from None
                await asyncio.sleep(delay)
        raise AssertionError("Unreachable retry state")  # pragma: no cover


_trial_context: ContextVar[TrialContext | None] = ContextVar("wardenbot_trial", default=None)


def current_trial_context() -> TrialContext | None:
    """Return the active campaign context, or None outside a campaign."""
    return _trial_context.get()


async def _run_cleanup(operation: Awaitable[object], cleanup_seconds: float) -> tuple[bool, bool]:
    """Drain a bounded cooperative cleanup even if its owner is cancelled again.

    Return (success, external_cancellation_seen). Cleanup diagnostics deliberately
    contain no exception object or text. Callers propagate cancellation afterward.
    """

    async def bounded() -> None:
        async with asyncio.timeout(cleanup_seconds):
            await operation

    task = asyncio.create_task(bounded())
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            break
    if task.cancelled():
        return False, cancelled
    return task.exception() is None, cancelled
