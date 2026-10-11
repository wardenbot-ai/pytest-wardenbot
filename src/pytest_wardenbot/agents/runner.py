"""Bounded execution and cleanup for one instrumented agent trial."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import uuid4

from pytest_wardenbot.agents.contracts import (
    AgentCapability,
    AgentTarget,
    HarnessTrace,
    Outcome,
    ReasonCode,
    RunLimits,
    RunResult,
    Scenario,
    TargetRun,
)
from pytest_wardenbot.agents.evaluation import evaluate, required_capabilities

Observer = Callable[[str], HarnessTrace]


def _error(
    scenario: Scenario,
    trial_id: str,
    limits: RunLimits,
    reason: ReasonCode,
    result: RunResult | None = None,
) -> RunResult:
    if result is None:
        return RunResult(
            trial_id=trial_id,
            scenario_id=scenario.id,
            scenario_version=scenario.version,
            outcome=Outcome.ERROR,
            reason_codes=(reason,),
            limits=limits,
        )
    # An execution/cleanup failure cannot erase an already observed violation.
    return replace(
        result,
        outcome=Outcome.VIOLATED if result.outcome is Outcome.VIOLATED else Outcome.ERROR,
        reason_codes=tuple(dict.fromkeys((*result.reason_codes, reason))),
    )


async def run_scenario(
    target: AgentTarget,
    scenario: Scenario,
    *,
    observe: Observer | None = None,
    limits: RunLimits | None = None,
) -> RunResult:
    """Run with fresh state, a deadline, authoritative observations and cleanup.

    ``observe`` is a trusted, local, nonblocking harness callback. Never populate
    it from model output. Without it, target claims cannot establish resistance.
    Each invocation receives an independent generated trial ID. Reset is called
    before execution and again afterward, including execution failure/cancel.

    The timeout covers pre-reset and target execution; cleanup has its own
    timeout. Async targets must cooperate with cancellation and enforce the
    supplied turn limit in their loop. This is not a process sandbox and cannot
    preempt blocking Python or an integration that suppresses cancellation.
    Unexpected exception messages/chains are not retained in public results.
    """
    limits = limits or RunLimits()
    trial_id = uuid4().hex
    try:
        capabilities = frozenset(target.capabilities)
        if not all(isinstance(item, AgentCapability) for item in capabilities):
            return _error(scenario, trial_id, limits, ReasonCode.INVALID_TARGET_RESULT)
    except Exception:
        return _error(scenario, trial_id, limits, ReasonCode.INVALID_TARGET_RESULT)

    if not required_capabilities(scenario).issubset(capabilities):
        return evaluate(
            scenario,
            TargetRun(),
            None,
            trial_id=trial_id,
            capabilities=capabilities,
            limits=limits,
        )

    result: RunResult | None = None
    target_run = TargetRun()
    phase = ReasonCode.RESET_ERROR
    execution_started = False
    cancelled = False
    try:
        async with asyncio.timeout(limits.timeout_seconds):
            await target.reset(trial_id)
            execution_started = True
            phase = ReasonCode.TARGET_ERROR
            target_run = await target.run(
                scenario.task, trial_id=trial_id, max_turns=limits.max_turns
            )
            phase = ReasonCode.OBSERVER_ERROR
            trace = observe(trial_id) if observe is not None else None
            result = evaluate(
                scenario,
                target_run,
                trace,
                trial_id=trial_id,
                capabilities=capabilities,
                limits=limits,
            )
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        reason = ReasonCode.TIMEOUT if isinstance(exc, TimeoutError) else phase
        # The sink may contain a confirmed effect even if execution then failed.
        if execution_started and observe is not None and phase is not ReasonCode.OBSERVER_ERROR:
            try:
                result = evaluate(
                    scenario,
                    target_run,
                    observe(trial_id),
                    trial_id=trial_id,
                    capabilities=capabilities,
                    limits=limits,
                )
            except Exception:
                result = None
        result = _error(scenario, trial_id, limits, reason, result)
    finally:
        try:
            async with asyncio.timeout(limits.cleanup_timeout_seconds):
                await target.reset(trial_id)
        except asyncio.CancelledError:
            # Cancellation remains cancellation, never a successful security run.
            raise
        except Exception:
            if not cancelled:
                result = _error(scenario, trial_id, limits, ReasonCode.CLEANUP_ERROR, result)

    assert result is not None
    return result
