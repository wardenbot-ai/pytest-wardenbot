"""Isolated agent campaigns with explicit accounting for every planned case."""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Iterable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pytest_wardenbot.agents._privacy import PrivacyPolicy, redact_text
from pytest_wardenbot.agents.budget import (
    BudgetExceeded,
    CampaignLimits,
    ExecutionBudget,
    TrialContext,
    _run_cleanup,
    _trial_context,
)
from pytest_wardenbot.agents.contracts import (
    AgentCapability,
    AgentTarget,
    Outcome,
    ReasonCode,
    RunLimits,
    RunResult,
    Scenario,
    _identifier,
)
from pytest_wardenbot.agents.reporting import result_to_dict
from pytest_wardenbot.agents.runner import Observer, _error, run_scenario


class TrialState(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NOT_RUN = "not_run"


@dataclass(frozen=True)
class TrialResources:
    """Resources owned by a case's async context manager, within this event loop."""

    target: AgentTarget = field(repr=False)
    observe: Observer | None = field(default=None, repr=False)


TrialFactory = Callable[[TrialContext], AbstractAsyncContextManager[TrialResources]]


@dataclass(frozen=True)
class CampaignCase:
    id: str = field(repr=False)
    scenario: Scenario = field(repr=False)
    factory: TrialFactory = field(repr=False)

    def __post_init__(self) -> None:
        _identifier(self.id)
        if not isinstance(self.scenario, Scenario) or not callable(self.factory):
            raise ValueError("A case requires a Scenario and an async resource factory")


@dataclass(frozen=True)
class TrialRecord:
    case_id: str = field(repr=False)
    state: TrialState
    result: RunResult | None = field(default=None, repr=False)
    reason_codes: tuple[ReasonCode, ...] = ()
    calls: int = 0
    turns: int = 0
    usage: dict[str, int | float] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CampaignResult:
    trials: tuple[TrialRecord, ...]
    limits: CampaignLimits
    calls: int
    turns: int
    usage: dict[str, int | float] | None = field(default=None, repr=False)
    usage_reported_trials: int = 0

    @property
    def planned(self) -> int:
        return len(self.trials)

    @property
    def not_run(self) -> int:
        return sum(row.state is TrialState.NOT_RUN for row in self.trials)

    @property
    def outcome_counts(self) -> dict[str, int]:
        return {
            outcome.value: sum(
                row.result is not None and row.result.outcome is outcome for row in self.trials
            )
            for outcome in Outcome
        }

    @property
    def task_successes(self) -> int:
        return sum(
            row.result is not None and row.result.task_succeeded is True for row in self.trials
        )


# Usage label text is application supplied. Public summaries expose only these
# numeric counters; internal usage mappings are never repr'd or dumped directly.
_PUBLIC_USAGE = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "estimated_cost_usd",
    }
)


def _public_usage(usage: dict[str, int | float] | None) -> dict[str, int | float] | None:
    if usage is None:
        return None
    return {key: value for key, value in usage.items() if key in _PUBLIC_USAGE} or None


def campaign_to_dict(
    result: CampaignResult, *, policy: PrivacyPolicy | None = None
) -> dict[str, Any]:
    """Serialize every planned row, with independent utility and security counts."""
    policy = policy or PrivacyPolicy()
    return {
        "schema_version": "1",
        "planned": result.planned,
        "not_run": result.not_run,
        "outcome_counts": result.outcome_counts,
        "task_successes": result.task_successes,
        "calls": result.calls,
        "turns": result.turns,
        "accounting_scope": "instrumented_operations_only",
        "limits": {
            "max_calls": result.limits.max_calls,
            "max_turns": result.limits.max_turns,
            "timeout_seconds": result.limits.timeout_seconds,
            "cleanup_timeout_seconds": result.limits.cleanup_timeout_seconds,
            "concurrency": result.limits.concurrency,
        },
        "usage": _public_usage(result.usage),
        "usage_reported_trials": result.usage_reported_trials,
        "cost_is_estimate": True,
        "trials": [
            {
                "case_id": redact_text(row.case_id, policy=policy),
                "state": row.state.value,
                "reason_codes": [reason.value for reason in row.reason_codes],
                "calls": row.calls,
                "turns": row.turns,
                "usage": _public_usage(row.usage),
                "result": result_to_dict(row.result, policy=policy) if row.result else None,
            }
            for row in result.trials
        ],
    }


def campaign_to_json(result: CampaignResult, *, policy: PrivacyPolicy | None = None) -> str:
    return json.dumps(campaign_to_dict(result, policy=policy), indent=2, allow_nan=False)


async def _close_factory(
    manager: AbstractAsyncContextManager[TrialResources], error: BaseException | None
) -> None:
    await manager.__aexit__(
        type(error) if error is not None else None,
        error,
        error.__traceback__ if error is not None else None,
    )


async def run_campaign(
    cases: Iterable[CampaignCase],
    *,
    limits: CampaignLimits | None = None,
    run_limits: RunLimits | None = None,
) -> CampaignResult:
    """Run each case at most once with a unique, factory-owned target instance.

    Run-wide accounting is cooperative: targets must use TrialContext.turn and
    TrialContext.call before work, and disable hidden SDK retry loops. The wall
    deadline cancels cooperative workers and drains their bounded cleanup. Python
    that blocks the event loop or suppresses cancellation cannot be preempted.
    External cancellation propagates only after owned tasks have been drained.
    """
    planned = tuple(cases)
    if any(not isinstance(case, CampaignCase) for case in planned):
        raise ValueError("Campaigns require CampaignCase entries")
    if len({case.id for case in planned}) != len(planned):
        raise ValueError("Campaign case IDs must be unique")
    limits = limits or CampaignLimits()
    run_limits = run_limits or RunLimits()
    budget = ExecutionBudget(limits)
    rows = [TrialRecord(case.id, TrialState.NOT_RUN) for case in planned]
    # Strong references prevent id reuse and reject sharing even across serial
    # trials. Ownership belongs to the factory, including clients and harnesses.
    seen_targets: list[AgentTarget] = []
    next_index = 0
    abort_reason: ReasonCode | None = None

    async def worker() -> None:
        nonlocal next_index
        while next_index < len(planned):
            reason = budget.stop_reason
            if reason is not None:
                return
            index = next_index
            next_index += 1
            case = planned[index]
            context = TrialContext(uuid4().hex, budget)
            token = _trial_context.set(context)
            manager: AbstractAsyncContextManager[TrialResources] | None = None
            entered = False
            result: RunResult | None = None
            exit_exception: BaseException | None = None
            state = TrialState.COMPLETED
            trial_limits = replace(
                run_limits,
                timeout_seconds=min(run_limits.timeout_seconds, budget.remaining_seconds or 1e-9),
                cleanup_timeout_seconds=min(
                    run_limits.cleanup_timeout_seconds, limits.cleanup_timeout_seconds
                ),
            )
            try:
                manager = case.factory(context)
                resources = await manager.__aenter__()
                entered = True
                if not isinstance(resources, TrialResources):
                    result = _error(
                        case.scenario, context.trial_id, trial_limits, ReasonCode.FACTORY_ERROR
                    )
                elif any(resources.target is target for target in seen_targets):
                    result = _error(
                        case.scenario, context.trial_id, trial_limits, ReasonCode.SHARED_TARGET
                    )
                else:
                    seen_targets.append(resources.target)
                    if AgentCapability.BUDGET_ACCOUNTING not in resources.target.capabilities:
                        result = replace(
                            _error(
                                case.scenario,
                                context.trial_id,
                                trial_limits,
                                ReasonCode.BUDGET_INSTRUMENTATION_REQUIRED,
                            ),
                            outcome=Outcome.UNSUPPORTED,
                        )
                    else:
                        result = await run_scenario(
                            resources.target,
                            case.scenario,
                            observe=resources.observe,
                            limits=trial_limits,
                        )
                        if result.turns > context.turns:
                            result = _error(
                                case.scenario,
                                context.trial_id,
                                trial_limits,
                                ReasonCode.BUDGET_INSTRUMENTATION_REQUIRED,
                                result,
                            )
            except asyncio.CancelledError as exc:
                exit_exception = exc
                state = TrialState.CANCELLED
                result = _error(
                    case.scenario,
                    context.trial_id,
                    trial_limits,
                    abort_reason or ReasonCode.CANCELLED,
                    context.result,
                )
            except Exception as exc:
                exit_exception = exc
                result = _error(
                    case.scenario,
                    context.trial_id,
                    trial_limits,
                    exc.reason if isinstance(exc, BudgetExceeded) else ReasonCode.FACTORY_ERROR,
                    context.result,
                )
            finally:
                if entered and manager is not None:
                    cleaned, cleanup_cancelled = await _run_cleanup(
                        _close_factory(manager, exit_exception),
                        limits.cleanup_timeout_seconds,
                    )
                    if not cleaned:
                        result = _error(
                            case.scenario,
                            context.trial_id,
                            trial_limits,
                            ReasonCode.CLEANUP_ERROR,
                            result,
                        )
                    if cleanup_cancelled:
                        state = TrialState.CANCELLED
                        result = _error(
                            case.scenario,
                            context.trial_id,
                            trial_limits,
                            abort_reason or ReasonCode.CANCELLED,
                            result,
                        )
                usage = dict(context.usage) if context.usage else result.usage if result else None
                rows[index] = TrialRecord(
                    case.id,
                    state,
                    result,
                    result.reason_codes if result is not None else (),
                    context.calls,
                    context.turns,
                    usage,
                )
                _trial_context.reset(token)
            if state is TrialState.CANCELLED:
                return

    tasks = [asyncio.create_task(worker()) for _ in range(min(limits.concurrency, len(planned)))]
    external_cancel = False
    try:
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=budget.remaining_seconds)
            if pending:
                abort_reason = ReasonCode.CAMPAIGN_DEADLINE
                for task in pending:
                    task.cancel()
    except asyncio.CancelledError:
        external_cancel = True
        abort_reason = ReasonCode.CANCELLED
        for task in tasks:
            if not task.done():
                task.cancel()
    finally:
        if tasks:
            group = asyncio.gather(*tasks, return_exceptions=True)
            while not group.done():
                try:
                    await asyncio.shield(group)
                except asyncio.CancelledError:
                    external_cancel = True
            group.result()
    if external_cancel:
        raise asyncio.CancelledError

    stop_reason = abort_reason or budget.stop_reason
    for index, row in enumerate(rows):
        if row.state is TrialState.NOT_RUN and stop_reason is not None:
            rows[index] = replace(row, reason_codes=(stop_reason,))
    usage: dict[str, int | float] | None = None
    usage_reported = 0
    overflow = False
    for row in rows:
        if row.usage is None:
            continue
        if _public_usage(row.usage) is not None:
            usage_reported += 1
        if usage is None:
            usage = {}
        for key, value in row.usage.items():
            try:
                total = usage.get(key, 0) + value
            except OverflowError:
                overflow = True
                continue
            if isinstance(total, float) and not math.isfinite(total):
                overflow = True
            else:
                usage[key] = total
    return CampaignResult(
        tuple(rows), limits, budget.calls, budget.turns, None if overflow else usage, usage_reported
    )
