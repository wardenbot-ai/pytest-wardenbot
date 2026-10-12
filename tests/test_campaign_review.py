"""Independent regression cases for cooperative campaign execution controls."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from pytest_wardenbot.agents import (
    AgentCapability,
    AgentEvent,
    AttackSurface,
    CampaignCase,
    EventKind,
    EventProvenance,
    EventTrust,
    HarnessTrace,
    Outcome,
    ReasonCode,
    RunLimits,
    Scenario,
    TargetRun,
    TrialResources,
    campaign_to_json,
    run_campaign,
    run_scenario,
)
from pytest_wardenbot.agents.budget import (
    BudgetExceeded,
    CampaignLimits,
    ExecutionBudget,
    RateLimitError,
    RetryPolicy,
    TrialContext,
)


@pytest.mark.asyncio
async def test_simultaneous_claims_never_start_more_calls_than_budget() -> None:
    budget = ExecutionBudget(CampaignLimits(max_calls=1, max_turns=64))
    entered = asyncio.Event()
    release = asyncio.Event()
    started: list[str] = []

    async def run(index: int) -> None:
        context = TrialContext(f"trial-{index}", budget)

        async def operation() -> None:
            started.append(context.trial_id)
            entered.set()
            await release.wait()

        await context.call(operation)

    tasks = [asyncio.create_task(run(index)) for index in range(64)]
    await entered.wait()
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert len(started) == budget.calls == 1
    assert sum(isinstance(result, BudgetExceeded) for result in results) == 63


def test_usage_overflow_rejects_whole_update_without_poisoning_counters() -> None:
    context = TrialContext("overflow", ExecutionBudget(CampaignLimits()))
    context.record_usage({"estimated_cost_usd": 1e308})
    with pytest.raises(ValueError):
        context.record_usage({"input_tokens": 7, "estimated_cost_usd": 1e308})
    assert context.usage == {"estimated_cost_usd": 1e308}


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -1, "1"])
@pytest.mark.parametrize("label", ["timeout_seconds", "cleanup_timeout_seconds"])
def test_campaign_timeout_limits_reject_invalid_numbers(label: str, value: object) -> None:
    with pytest.raises(ValueError):
        CampaignLimits(**{label: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, False, float("nan"), float("inf"), -1, 0, 1.5])
@pytest.mark.parametrize("label", ["max_calls", "max_turns", "concurrency"])
def test_campaign_integer_limits_reject_invalid_numbers(label: str, value: object) -> None:
    with pytest.raises(ValueError):
        CampaignLimits(**{label: value})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_retry_supplies_same_actual_idempotency_key_and_accounts_attempts() -> None:
    context = TrialContext("keyed-write", ExecutionBudget(CampaignLimits()))
    received_keys: list[str] = []
    effects: set[str] = set()

    async def operation(*, idempotency_key: str) -> str:
        received_keys.append(idempotency_key)
        effects.add(idempotency_key)
        if len(received_keys) == 1:
            # The service accepted the first write but its response was lost.
            raise RateLimitError()
        return "already-applied"

    result = await context.call(
        operation,
        retry=RetryPolicy(
            max_retries=1,
            safe_to_retry=True,
            side_effecting=True,
            idempotent=True,
            idempotency_key="stable-operation-key",
        ),
    )
    assert result == "already-applied"
    assert received_keys == ["stable-operation-key", "stable-operation-key"]
    assert len(effects) == 1
    assert context.calls == context.budget.calls == 2


@pytest.mark.asyncio
async def test_second_external_cancellation_still_drains_cooperative_cleanup() -> None:
    class Target:
        name = "repeat-cancel"
        capabilities = frozenset(AgentCapability)

        def __init__(self) -> None:
            self.resets = 0
            self.run_entered = asyncio.Event()
            self.cleanup_entered = asyncio.Event()
            self.cleanup_release = asyncio.Event()
            self.cleaned = False

        async def reset(self, trial_id: str) -> None:
            self.resets += 1
            if self.resets == 2:
                self.cleanup_entered.set()
                await self.cleanup_release.wait()
                self.cleaned = True

        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            self.run_entered.set()
            await asyncio.Event().wait()
            return TargetRun()  # pragma: no cover

    target = Target()
    scenario = Scenario(
        "cancellation", "1", "Read a note", AttackSurface.TOOL_RESULT, forbidden_tool="write"
    )
    task = asyncio.create_task(
        run_scenario(target, scenario, limits=RunLimits(cleanup_timeout_seconds=1))
    )
    try:
        async with asyncio.timeout(2):
            await target.run_entered.wait()
            task.cancel()
            await target.cleanup_entered.wait()
            task.cancel()
            target.cleanup_release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        target.cleanup_release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert target.resets == 2
    assert target.cleaned


@pytest.mark.asyncio
async def test_campaign_refuses_legacy_target_before_reset_or_execution() -> None:
    calls: list[str] = []

    class LegacyTarget:
        name = "legacy"
        capabilities = frozenset(AgentCapability) - {AgentCapability.BUDGET_ACCOUNTING}

        async def reset(self, trial_id: str) -> None:
            calls.append("reset")

        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            calls.append("run")
            return TargetRun(turns=1)

    @asynccontextmanager
    async def factory(context: TrialContext):
        yield TrialResources(LegacyTarget())

    scenario = Scenario(
        "legacy", "1", "Read a note", AttackSurface.TOOL_RESULT, forbidden_tool="write"
    )
    result = await run_campaign([CampaignCase("legacy", scenario, factory)])
    row = result.trials[0]
    assert row.result is not None and row.result.outcome is Outcome.UNSUPPORTED
    assert ReasonCode.BUDGET_INSTRUMENTATION_REQUIRED in row.reason_codes
    assert not calls


@pytest.mark.asyncio
async def test_factory_budget_failure_retains_actual_budget_reason() -> None:
    async def operation() -> None:
        return None

    @asynccontextmanager
    async def factory(context: TrialContext):
        await context.call(operation)
        await context.call(operation)
        yield TrialResources(None)  # type: ignore[arg-type]  # pragma: no cover

    scenario = Scenario(
        "startup", "1", "Read a note", AttackSurface.TOOL_RESULT, forbidden_tool="write"
    )
    result = await run_campaign(
        [CampaignCase("startup", scenario, factory)], limits=CampaignLimits(max_calls=1)
    )
    assert result.calls == 1
    assert ReasonCode.CALL_BUDGET_EXHAUSTED in result.trials[0].reason_codes
    assert ReasonCode.FACTORY_ERROR not in result.trials[0].reason_codes


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_accounting_failure_or_deadline_preserves_effect_and_factory_semantics(
    cancelled: bool,
) -> None:
    seen_cancellations: list[str] = []
    scenario = Scenario(
        "effect", "1", "Read a note", AttackSurface.TOOL_RESULT, forbidden_tool="write"
    )

    @asynccontextmanager
    async def factory(context: TrialContext):
        class Target:
            name = "effect-target"
            capabilities = frozenset(AgentCapability)

            async def reset(self, trial_id: str) -> None:
                return None

            async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
                if cancelled:
                    context.turn()
                    await context.call(lambda: asyncio.Event().wait())
                return TargetRun(turns=1)

        def observe(trial_id: str) -> HarnessTrace:
            return HarnessTrace(
                trial_id,
                (
                    AgentEvent(
                        trial_id,
                        EventKind.TOOL_EFFECT,
                        EventProvenance.HARNESS,
                        EventTrust.OBSERVED,
                        name="write",
                    ),
                ),
                complete=True,
            )

        try:
            yield TrialResources(Target(), observe)
        except asyncio.CancelledError:
            seen_cancellations.append(context.trial_id)
            raise

    result = await run_campaign(
        [CampaignCase("effect", scenario, factory)], limits=CampaignLimits(timeout_seconds=0.05)
    )
    row = result.trials[0]
    assert row.result is not None and row.result.outcome is Outcome.VIOLATED
    assert ReasonCode.FORBIDDEN_TOOL_EFFECT in row.reason_codes
    expected = (
        ReasonCode.CAMPAIGN_DEADLINE if cancelled else ReasonCode.BUDGET_INSTRUMENTATION_REQUIRED
    )
    assert expected in row.reason_codes
    assert bool(seen_cancellations) is cancelled


@pytest.mark.asyncio
async def test_factory_receives_escaped_error_without_exporting_private_exception() -> None:
    error = RuntimeError("synthetic-private-factory-body-value")
    received: list[BaseException] = []

    class Target:
        name = "invalid-capabilities"

        @property
        def capabilities(self):
            raise error

    @asynccontextmanager
    async def factory(context: TrialContext):
        try:
            yield TrialResources(Target())  # type: ignore[arg-type]
        except RuntimeError as exc:
            received.append(exc)
            raise

    scenario = Scenario(
        "factory-error", "1", "Read a note", AttackSurface.TOOL_RESULT, forbidden_tool="write"
    )
    result = await run_campaign([CampaignCase("factory-error", scenario, factory)])
    assert received == [error]
    assert result.trials[0].reason_codes == (ReasonCode.FACTORY_ERROR,)
    assert "synthetic-private" not in campaign_to_json(result) + repr(result)
