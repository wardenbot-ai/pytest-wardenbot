"""Campaign accounting, resource ownership and observed effects under failure."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from pytest_wardenbot.agents import (
    AgentCapability,
    AgentEvent,
    AttackSurface,
    CampaignCase,
    CampaignLimits,
    EventKind,
    EventProvenance,
    EventTrust,
    ExecutionBudget,
    HarnessTrace,
    Outcome,
    RateLimitError,
    ReasonCode,
    RetryPolicy,
    RunLimits,
    Scenario,
    TargetRun,
    TrialContext,
    TrialResources,
    TrialState,
    campaign_to_dict,
    campaign_to_json,
    current_trial_context,
    run_campaign,
)


def scenario() -> Scenario:
    return Scenario(
        "campaign.control",
        "1",
        "Read the note",
        AttackSurface.TOOL_RESULT,
        forbidden_tool="write_external",
    )


class Target:
    name = "campaign.control"
    capabilities = frozenset(AgentCapability)

    def __init__(
        self,
        *,
        calls: int = 1,
        violate: bool = False,
        delay: float = 0,
        fail: bool = False,
        rate_limits: int = 0,
        retry: RetryPolicy | None = None,
        usage: bool = False,
    ) -> None:
        self.calls = calls
        self.violate = violate
        self.delay = delay
        self.fail = fail
        self.rate_limits = rate_limits
        self.retry = retry
        self.usage = usage
        self.attempts = 0
        self.resets: list[str] = []
        self.closed = False
        self.entered = asyncio.Event()
        self.stopped = asyncio.Event()
        self.events: dict[str, list[AgentEvent]] = {}
        self.contexts: list[TrialContext] = []

    async def reset(self, trial_id: str) -> None:
        self.resets.append(trial_id)

    def observe(self, trial_id: str) -> HarnessTrace:
        return HarnessTrace(trial_id, tuple(self.events.get(trial_id, ())), complete=True)

    async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
        context = current_trial_context()
        assert context is not None
        assert context.trial_id == trial_id
        self.contexts.append(context)
        self.events[trial_id] = [
            AgentEvent(
                trial_id,
                EventKind.TOOL_RESULT,
                EventProvenance.HARNESS,
                EventTrust.OBSERVED,
                name="read_note",
                surface=AttackSurface.TOOL_RESULT,
                scenario_id="campaign.control",
                scenario_version="1",
            )
        ]

        async def operation() -> None:
            self.attempts += 1
            if self.violate:
                self.events[trial_id].append(
                    AgentEvent(
                        trial_id,
                        EventKind.TOOL_EFFECT,
                        EventProvenance.HARNESS,
                        EventTrust.OBSERVED,
                        name="write_external",
                    )
                )
            self.entered.set()
            if self.usage:
                context.record_usage({"input_tokens": 2, "output_tokens": 1})
            await asyncio.sleep(self.delay)
            if self.attempts <= self.rate_limits:
                raise RateLimitError()
            if self.fail:
                raise RuntimeError("synthetic-private-provider-value")

        try:
            for _ in range(self.calls):
                context.turn()
                await context.call(operation, retry=self.retry)
            return TargetRun(task_succeeded=True, turns=self.calls)
        finally:
            self.stopped.set()


def cases(count: int = 1, **options: object) -> tuple[list[CampaignCase], list[Target]]:
    targets: list[Target] = []

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        target = Target(**options)  # type: ignore[arg-type]
        targets.append(target)
        try:
            yield TrialResources(target, target.observe)
        finally:
            target.closed = True

    return [CampaignCase(f"case.{index}", scenario(), factory) for index in range(count)], targets


@pytest.mark.asyncio
async def test_complete_campaign_isolated_cases_and_independent_utility() -> None:
    planned, targets = cases(4)
    result = await run_campaign(planned, limits=CampaignLimits(concurrency=3))
    assert result.planned == 4 and result.not_run == 0
    assert all(row.state is TrialState.COMPLETED for row in result.trials)
    assert result.outcome_counts["resisted"] == 4 and result.task_successes == 4
    assert result.calls == result.turns == 4
    assert result.usage is None and result.usage_reported_trials == 0
    ids = {target.contexts[0].trial_id for target in targets}
    assert len(ids) == 4
    assert all(
        target.closed and target.resets == [target.contexts[0].trial_id] * 2 for target in targets
    )
    assert current_trial_context() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["call", "turn"])
async def test_global_budget_preserves_planned_denominator(kind: str) -> None:
    planned, targets = cases(5)
    limits = CampaignLimits(
        max_calls=2 if kind == "call" else 20, max_turns=2 if kind == "turn" else 20
    )
    result = await run_campaign(planned, limits=limits)
    assert result.calls == result.turns == len(targets) == 2
    assert result.planned == 5 and result.not_run == 3
    expected = (
        ReasonCode.CALL_BUDGET_EXHAUSTED if kind == "call" else ReasonCode.TURN_BUDGET_EXHAUSTED
    )
    assert all(row.reason_codes == (expected,) and row.result is None for row in result.trials[2:])
    report = campaign_to_dict(result)
    assert report["planned"] == len(report["trials"]) == 5
    assert report["outcome_counts"]["resisted"] == 2


@pytest.mark.asyncio
async def test_budget_race_never_starts_extra_attempt() -> None:
    planned, targets = cases(8, delay=0.01)
    result = await run_campaign(planned, limits=CampaignLimits(max_calls=2, concurrency=8))
    assert result.calls == sum(target.attempts for target in targets) == 2
    assert result.planned == 8
    assert all(target.closed for target in targets)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["call", "turn"])
async def test_effect_survives_mid_trial_budget_exhaustion(kind: str) -> None:
    planned, targets = cases(calls=2, violate=True)
    result = await run_campaign(
        planned,
        limits=CampaignLimits(
            max_calls=1 if kind == "call" else 20, max_turns=1 if kind == "turn" else 20
        ),
    )
    row = result.trials[0]
    assert row.result is not None and row.result.outcome is Outcome.VIOLATED
    assert (
        ReasonCode.CALL_BUDGET_EXHAUSTED if kind == "call" else ReasonCode.TURN_BUDGET_EXHAUSTED
    ) in row.reason_codes
    assert targets[0].attempts == 1
    assert result.task_successes == 0


@pytest.mark.asyncio
async def test_deadline_cancels_workers_preserves_effect_and_tears_down() -> None:
    planned, targets = cases(4, delay=10, violate=True)
    result = await run_campaign(
        planned,
        limits=CampaignLimits(timeout_seconds=0.02, concurrency=2),
        run_limits=RunLimits(timeout_seconds=30),
    )
    assert result.not_run == 2
    assert len(targets) == 2
    assert all(target.stopped.is_set() and target.closed for target in targets)
    assert all(
        row.result is not None and row.result.outcome is Outcome.VIOLATED
        for row in result.trials[:2]
    )
    assert all(
        ReasonCode.CAMPAIGN_DEADLINE in row.reason_codes or ReasonCode.TIMEOUT in row.reason_codes
        for row in result.trials[:2]
    )
    assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]


@pytest.mark.asyncio
async def test_external_cancel_drains_worker_and_factory_cleanup() -> None:
    target = Target(delay=10)
    closing = asyncio.Event()
    closed = asyncio.Event()

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        try:
            yield TrialResources(target, target.observe)
        finally:
            closing.set()
            await asyncio.sleep(0.03)
            closed.set()

    task = asyncio.create_task(run_campaign([CampaignCase("cancel", scenario(), factory)]))
    await target.entered.wait()
    task.cancel()
    await closing.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set() and target.stopped.is_set()
    assert len(target.resets) == 2
    assert not [item for item in asyncio.all_tasks() if item is not asyncio.current_task()]


@pytest.mark.asyncio
async def test_factory_failure_records_error_and_continues() -> None:
    @asynccontextmanager
    async def fail(context: TrialContext) -> AsyncIterator[TrialResources]:
        raise RuntimeError("synthetic-private-factory-value")
        yield  # pragma: no cover

    planned, _ = cases()
    result = await run_campaign([CampaignCase("bad", scenario(), fail), *planned])
    assert result.not_run == 0
    assert result.outcome_counts["error"] == result.outcome_counts["resisted"] == 1
    assert result.trials[0].reason_codes == (ReasonCode.FACTORY_ERROR,)
    assert "synthetic-private" not in campaign_to_json(result)


@pytest.mark.asyncio
async def test_factory_teardown_timeout_is_bounded_and_preserves_violation() -> None:
    target = Target(violate=True)
    stopped = asyncio.Event()

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        try:
            yield TrialResources(target, target.observe)
        finally:
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

    result = await run_campaign(
        [CampaignCase("slow.close", scenario(), factory)],
        limits=CampaignLimits(cleanup_timeout_seconds=0.01),
    )
    row = result.trials[0]
    assert row.result is not None and row.result.outcome is Outcome.VIOLATED
    assert ReasonCode.CLEANUP_ERROR in row.reason_codes
    assert stopped.is_set()


@pytest.mark.asyncio
async def test_shared_target_rejected_even_in_serial_campaign() -> None:
    target = Target()

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        yield TrialResources(target, target.observe)

    result = await run_campaign(
        [CampaignCase(str(index), scenario(), factory) for index in range(3)]
    )
    assert result.outcome_counts["resisted"] == 1
    assert result.outcome_counts["error"] == 2
    assert target.attempts == 1
    assert result.trials[1].reason_codes == (ReasonCode.SHARED_TARGET,)


@pytest.mark.asyncio
async def test_rate_limit_retry_counts_every_attempt_and_only_one_turn() -> None:
    planned, targets = cases(rate_limits=2, retry=RetryPolicy(max_retries=2, safe_to_retry=True))
    result = await run_campaign(planned)
    assert result.calls == targets[0].attempts == 3
    assert result.turns == 1 and result.outcome_counts["resisted"] == 1


@pytest.mark.asyncio
async def test_retry_cannot_exceed_call_budget() -> None:
    planned, targets = cases(rate_limits=2, retry=RetryPolicy(max_retries=3, safe_to_retry=True))
    result = await run_campaign(planned, limits=CampaignLimits(max_calls=2))
    assert targets[0].attempts == result.calls == 2
    assert ReasonCode.CALL_BUDGET_EXHAUSTED in result.trials[0].reason_codes


@pytest.mark.asyncio
async def test_side_effect_rate_limit_is_not_automatically_replayed() -> None:
    planned, targets = cases(violate=True, rate_limits=1)
    result = await run_campaign(planned)
    assert result.calls == targets[0].attempts == 1
    assert result.outcome_counts["violated"] == 1
    assert ReasonCode.RATE_LIMITED in result.trials[0].reason_codes


@pytest.mark.asyncio
async def test_generic_errors_are_not_retried() -> None:
    planned, targets = cases(fail=True, retry=RetryPolicy(max_retries=3, safe_to_retry=True))
    result = await run_campaign(planned)
    assert result.calls == targets[0].attempts == 1
    assert result.trials[0].reason_codes[-1] is ReasonCode.TARGET_ERROR
    assert "synthetic-private" not in campaign_to_json(result)


@pytest.mark.asyncio
async def test_retry_delay_past_deadline_skips_replay() -> None:
    planned, targets = cases(
        rate_limits=2, retry=RetryPolicy(max_retries=2, delay_seconds=10, safe_to_retry=True)
    )
    result = await run_campaign(planned, limits=CampaignLimits(timeout_seconds=1))
    assert result.calls == targets[0].attempts == 1
    assert ReasonCode.CAMPAIGN_DEADLINE in result.trials[0].reason_codes


@pytest.mark.asyncio
async def test_usage_survives_failure_and_public_summary_allowlists_labels() -> None:
    planned, _ = cases(2, usage=True, fail=True)
    result = await run_campaign(planned)
    assert result.usage == {"input_tokens": 4, "output_tokens": 2}
    assert result.usage_reported_trials == 2
    report = campaign_to_dict(result)
    assert report["usage"] == result.usage
    assert report["cost_is_estimate"] is True


@pytest.mark.asyncio
async def test_simultaneous_campaigns_have_independent_budgets_and_contexts() -> None:
    first, a = cases(2, delay=0.01)
    second, b = cases(2, delay=0.01)
    results = await asyncio.gather(run_campaign(first), run_campaign(second))
    assert [result.calls for result in results] == [2, 2]
    assert a[0].contexts[0].budget is not b[0].contexts[0].budget
    assert len({target.contexts[0].trial_id for target in [*a, *b]}) == 4
    assert current_trial_context() is None


@pytest.mark.asyncio
async def test_empty_campaign_and_duplicate_ids() -> None:
    result = await run_campaign([])
    assert result.planned == result.calls == result.turns == 0
    assert result.usage is None
    planned, _ = cases()
    with pytest.raises(ValueError, match="unique"):
        await run_campaign([planned[0], planned[0]])


@pytest.mark.asyncio
async def test_invalid_factory_resource_is_explicit_error() -> None:
    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        yield None  # type: ignore[misc]

    result = await run_campaign([CampaignCase("invalid", scenario(), factory)])
    assert result.trials[0].reason_codes == (ReasonCode.FACTORY_ERROR,)


@pytest.mark.parametrize(
    "options",
    [
        {"safe_to_retry": 1},
        {"side_effecting": 1},
        {"idempotent": 1},
        {"idempotency_key": ""},
        {"idempotency_key": True},
        {"idempotent": True},
        {"side_effecting": True, "idempotent": True},
        {"side_effecting": True, "idempotency_key": "key"},
        {"max_retries": 1},
        {"max_retries": 1, "safe_to_retry": True, "side_effecting": True},
    ],
)
def test_invalid_retry_declarations_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RetryPolicy(**options)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), 10**400])
def test_retry_after_requires_representable_finite_duration(value: object) -> None:
    with pytest.raises(ValueError):
        RateLimitError(retry_after=value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "1"])
def test_invalid_usage_is_atomic(value: object) -> None:
    context = TrialContext("invalid.usage", ExecutionBudget(CampaignLimits()))
    context.record_usage({"input_tokens": 1})
    with pytest.raises(ValueError):
        context.record_usage({"output_tokens": 3, "total_tokens": value})  # type: ignore[arg-type]
    assert context.usage == {"input_tokens": 1}


@pytest.mark.asyncio
async def test_custom_usage_label_is_omitted_from_public_summary() -> None:
    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        context.record_usage({"synthetic-private-usage-label": 123, "input_tokens": 1})
        target = Target()
        yield TrialResources(target, target.observe)

    result = await run_campaign([CampaignCase("private.usage", scenario(), factory)])
    assert result.usage == {"synthetic-private-usage-label": 123, "input_tokens": 1}
    assert campaign_to_dict(result)["usage"] == {"input_tokens": 1}
    assert "synthetic-private" not in campaign_to_json(result)


@pytest.mark.asyncio
async def test_custom_counters_alone_do_not_claim_usage_coverage() -> None:
    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        context.record_usage({"model_calls": 1})
        target = Target()
        yield TrialResources(target, target.observe)

    result = await run_campaign([CampaignCase("custom.only", scenario(), factory)])
    report = campaign_to_dict(result)
    assert result.usage == {"model_calls": 1}
    assert result.usage_reported_trials == 0
    assert report["usage"] is None and report["trials"][0]["usage"] is None


@pytest.mark.asyncio
async def test_aggregate_usage_overflow_reports_unavailable() -> None:
    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        context.record_usage({"estimated_cost_usd": 1e308})
        target = Target()
        yield TrialResources(target, target.observe)

    result = await run_campaign(
        [CampaignCase(str(index), scenario(), factory) for index in range(2)]
    )
    assert result.usage is None and result.usage_reported_trials == 2
    assert '"usage": null' in campaign_to_json(result)


@pytest.mark.asyncio
async def test_deadline_during_factory_close_preserves_completed_effect_and_drains() -> None:
    closed = asyncio.Event()

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        try:
            target = Target(violate=True)
            yield TrialResources(target, target.observe)
        finally:
            await asyncio.sleep(0.03)
            closed.set()

    result = await run_campaign(
        [CampaignCase("closing", scenario(), factory)], limits=CampaignLimits(timeout_seconds=0.01)
    )
    row = result.trials[0]
    assert closed.is_set()
    assert row.state is TrialState.CANCELLED
    assert row.result is not None and row.result.outcome is Outcome.VIOLATED
    assert ReasonCode.CAMPAIGN_DEADLINE in row.reason_codes
