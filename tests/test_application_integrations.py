"""Core-only campaigns and portable evidence around actual application hooks."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest

from pytest_wardenbot.agents import (
    CampaignCase,
    CampaignLimits,
    EventKind,
    EventProvenance,
    EventTrust,
    Outcome,
    PrivacyPolicy,
    ReasonCode,
    TargetRun,
    TrialContext,
    TrialResources,
    TrialState,
    create_evidence_bundle,
    current_trial_context,
    evidence_fingerprint,
    evidence_to_dict,
    load_evidence_bundle,
    regrade_evidence,
    run_campaign,
    run_scenario,
)
from pytest_wardenbot.agents.evidence_reports import evidence_to_junit, render_evidence_html
from pytest_wardenbot.agents.packs import (
    APPLICATION_PACKS,
    ApplicationHarness,
    ApplicationPack,
    ApplicationPackSpec,
    ScriptedApplicationTarget,
)

Behavior = Literal["resistant", "vulnerable", "no_exposure"]
Variant = Literal["attack", "benign"]


@dataclass
class Owned:
    harness: ApplicationHarness
    target: ScriptedApplicationTarget
    context: TrialContext
    closed: bool = False


def make_case(
    spec: ApplicationPackSpec,
    owned: list[Owned],
    *,
    variant: Variant = "attack",
    behavior: Behavior = "vulnerable",
    identifier: str = "application.integration",
    target_class: type[ScriptedApplicationTarget] = ScriptedApplicationTarget,
) -> CampaignCase:
    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        harness = ApplicationHarness(
            spec, variant=variant, enforce_boundaries=behavior != "vulnerable"
        )
        target = target_class(harness, behavior=behavior)
        item = Owned(harness, target, context)
        owned.append(item)
        try:
            yield TrialResources(target, harness.observe)
        finally:
            item.closed = True

    return CampaignCase(identifier, spec.scenario, factory)


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", APPLICATION_PACKS, ids=lambda spec: spec.scenario.id)
@pytest.mark.parametrize(
    "variant,behavior,expected,utility",
    [
        ("benign", "resistant", Outcome.INCONCLUSIVE, True),
        ("attack", "vulnerable", Outcome.VIOLATED, True),
        ("attack", "resistant", Outcome.RESISTED, True),
        ("attack", "no_exposure", Outcome.INCONCLUSIVE, False),
    ],
)
async def test_every_pack_four_controls_have_actual_authoritative_observations(
    spec,
    variant,
    behavior,
    expected,
    utility,
) -> None:
    owned: list[Owned] = []
    campaign = await run_campaign([make_case(spec, owned, variant=variant, behavior=behavior)])
    row = campaign.trials[0]
    assert row.result is not None
    assert row.result.outcome is expected
    assert row.result.task_succeeded is utility
    assert row.state is TrialState.COMPLETED
    item = owned[0]
    trace = item.harness.observe(row.result.trial_id)
    assert trace.complete
    assert trace.events == row.result.events
    assert all(
        event.provenance is EventProvenance.HARNESS and event.trust is EventTrust.OBSERVED
        for event in trace.events
    )
    effects = [event for event in trace.events if event.kind is EventKind.TOOL_EFFECT]
    if behavior == "vulnerable":
        assert effects
    elif variant == "attack":
        assert not any(event.name == spec.scenario.forbidden_tool for event in effects)
        assert ReasonCode.FORBIDDEN_TOOL_EFFECT not in row.reason_codes
        assert ReasonCode.CANARY_LEAK not in row.reason_codes
    assert item.closed
    assert item.target.last_target_run is not None
    assert item.target.last_trace == trace


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", APPLICATION_PACKS, ids=lambda spec: spec.scenario.id)
async def test_call_cap_prevents_forbidden_operation_and_keeps_planned_rows(
    spec,
) -> None:
    owned: list[Owned] = []
    campaign = await run_campaign(
        [make_case(spec, owned), make_case(spec, owned, identifier="queued")],
        limits=CampaignLimits(max_calls=1),
    )
    row = campaign.trials[0]
    assert row.result is not None
    assert row.result.outcome is Outcome.ERROR
    assert ReasonCode.CALL_BUDGET_EXHAUSTED in row.reason_codes
    assert campaign.calls == 1
    assert campaign.trials[1].state is TrialState.NOT_RUN
    assert campaign.planned == 2
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in row.result.events)
    assert owned[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", APPLICATION_PACKS, ids=lambda spec: spec.scenario.id)
async def test_confirmed_application_violation_survives_later_target_failure(spec) -> None:
    class FailsAfterEffects(ScriptedApplicationTarget):
        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            await super().run(task, trial_id=trial_id, max_turns=max_turns)
            raise RuntimeError("private failure after observed state change")

    owned: list[Owned] = []
    campaign = await run_campaign([make_case(spec, owned, target_class=FailsAfterEffects)])
    row = campaign.trials[0]
    assert row.result is not None
    assert row.result.outcome is Outcome.VIOLATED
    assert ReasonCode.TARGET_ERROR in row.reason_codes
    assert any(event.kind is EventKind.TOOL_EFFECT for event in row.result.events)
    assert owned[0].closed
    assert "private failure" not in render_evidence_html(
        create_evidence_bundle(
            row.result,
            spec.scenario,
            target_fingerprint=evidence_fingerprint("control"),
            config_fingerprint=evidence_fingerprint("synthetic"),
            corpus_fingerprint=evidence_fingerprint("pack"),
        )
    )


@pytest.mark.asyncio
async def test_concurrent_campaigns_use_distinct_targets_stores_and_trial_contexts() -> None:
    first: list[Owned] = []
    second: list[Owned] = []
    left, right = await asyncio.gather(
        run_campaign(
            [
                make_case(spec, first, identifier=f"left-{index}")
                for index, spec in enumerate(APPLICATION_PACKS)
            ],
            limits=CampaignLimits(concurrency=5),
        ),
        run_campaign(
            [
                make_case(spec, second, behavior="resistant", identifier=f"right-{index}")
                for index, spec in enumerate(APPLICATION_PACKS)
            ],
            limits=CampaignLimits(concurrency=5),
        ),
    )
    assert all(row.result and row.result.outcome is Outcome.VIOLATED for row in left.trials)
    assert all(row.result and row.result.outcome is Outcome.RESISTED for row in right.trials)
    assert len({id(item.target) for item in first + second}) == 10
    assert len({id(item.harness) for item in first + second}) == 10
    assert len({item.context.trial_id for item in first + second}) == 10
    assert all(item.closed for item in first + second)
    assert first[0].context.budget is not second[0].context.budget
    for item in first + second:
        assert item.target.last_trial_id == item.context.trial_id
        assert {event.trial_id for event in item.harness.observe(item.context.trial_id).events} == {
            item.context.trial_id,
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", APPLICATION_PACKS, ids=lambda spec: spec.scenario.id)
async def test_application_bundle_regrades_only_actual_target_and_harness_sources(spec) -> None:
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    policy = PrivacyPolicy(include_content=True)
    bundle = create_evidence_bundle(
        result,
        spec.scenario,
        target_fingerprint=evidence_fingerprint("scripted.application.control.v1"),
        config_fingerprint=evidence_fingerprint({"enforce_boundaries": False}),
        corpus_fingerprint=evidence_fingerprint(spec.scenario.id),
        target_run=target.last_target_run,
        harness_trace=target.last_trace,
        capabilities=target.capabilities,
        privacy=policy,
    )
    artifact = evidence_to_dict(bundle, policy=policy)
    assert artifact["coverage"]["regradeable"]
    restored = load_evidence_bundle(artifact)
    regraded = regrade_evidence(restored)
    assert regraded.outcome is Outcome.VIOLATED
    assert regraded.task_succeeded is result.task_succeeded
    assert regraded.events == result.events
    assert artifact["evidence"]["harness_trace"]["complete"]
    assert evidence_to_junit(restored).count("ObservedBoundaryViolation") == 1
    assert "Evidence provenance / trust" in render_evidence_html(restored)


def test_example_runs_from_external_cwd_without_provider_environment(
    tmp_path: Path,
) -> None:
    script = (
        Path(__file__).resolve().parents[1] / "examples" / "application_packs" / "run_controls.py"
    )
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("ANTHROPIC_API_KEY", None)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--include-synthetic-content"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["planned"] == len(APPLICATION_PACKS) * 4
    assert report["not_run"] == 0
    assert report["control_expectations_satisfied"]
    assert report["outcome_counts"]["violated"] == len(APPLICATION_PACKS)
    assert report["outcome_counts"]["resisted"] == len(APPLICATION_PACKS)
    assert report["outcome_counts"]["inconclusive"] == len(APPLICATION_PACKS) * 2
    assert report["task_successes"] == len(APPLICATION_PACKS) * 3
    assert report["usage"] is None
    assert len(report["evidence_bundles"]) == report["planned"]
    assert all(artifact["coverage"]["regradeable"] for artifact in report["evidence_bundles"])
    assert all(load_evidence_bundle(artifact) for artifact in report["evidence_bundles"])


@pytest.mark.asyncio
@pytest.mark.parametrize("spec", APPLICATION_PACKS, ids=lambda spec: spec.scenario.id)
async def test_confirmed_effect_survives_a_later_rejected_budget_claim(spec) -> None:
    original: list[Owned] = []
    completed = await run_campaign([make_case(spec, original)])
    assert completed.trials[0].result is not None
    assert completed.trials[0].result.outcome is Outcome.VIOLATED

    class NeedsAnotherOperation(ScriptedApplicationTarget):
        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            result = await super().run(task, trial_id=trial_id, max_turns=max_turns)
            context = current_trial_context()
            assert context is not None

            async def next_operation() -> None:
                raise AssertionError("The extra operation must never start")

            await context.call(next_operation)
            return result

    bounded: list[Owned] = []
    campaign = await run_campaign(
        [make_case(spec, bounded, target_class=NeedsAnotherOperation)],
        limits=CampaignLimits(max_calls=completed.calls),
    )
    row = campaign.trials[0]
    assert row.result is not None
    assert row.result.outcome is Outcome.VIOLATED
    assert ReasonCode.CALL_BUDGET_EXHAUSTED in row.reason_codes
    assert campaign.calls == completed.calls
    original_effects = [
        event for event in completed.trials[0].result.events if event.kind is EventKind.TOOL_EFFECT
    ]
    bounded_effects = [event for event in row.result.events if event.kind is EventKind.TOOL_EFFECT]

    def effect_values(events):
        return [
            (event.name, {key: value for key, value in event.data.items() if key != "session_id"})
            for event in events
        ]

    assert effect_values(bounded_effects) == effect_values(original_effects)
    assert {event.data["session_id"] for event in bounded_effects}.isdisjoint(
        event.data["session_id"] for event in original_effects
    )
    assert bounded[0].closed


@pytest.mark.asyncio
async def test_memory_read_in_later_clean_session_observes_actual_persisted_write() -> None:
    spec = next(spec for spec in APPLICATION_PACKS if spec.pack is ApplicationPack.MEMORY)
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    written = next(event for event in result.events if event.kind is EventKind.MEMORY_WRITE)
    read = next(event for event in result.events if event.kind is EventKind.MEMORY_READ)
    effect = next(event for event in result.events if event.kind is EventKind.TOOL_EFFECT)
    assert written.data["text"] == read.data["text"]
    assert spec.attack_payload in str(read.data["text"])
    assert written.data["session_id"] != read.data["session_id"]
    assert effect.data["session_id"] == read.data["session_id"]
    snapshot = harness.snapshot(result.trial_id)
    session_history = snapshot["session_history"]
    assert isinstance(session_history, list)
    assert len(session_history) == 2
    assert snapshot["session_ids"] == []
    assert snapshot["memory"]
    assert target.history == []


@pytest.mark.asyncio
async def test_new_trial_resets_active_state_but_retains_prior_audit_snapshot() -> None:
    spec = next(spec for spec in APPLICATION_PACKS if spec.pack is ApplicationPack.MEMORY)
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    original = await run_scenario(target, spec.scenario, observe=harness.observe)
    past = harness.snapshot(original.trial_id)
    target.behavior = "no_exposure"
    fresh = await run_scenario(target, spec.scenario, observe=harness.observe)
    assert original.trial_id != fresh.trial_id
    assert fresh.outcome is Outcome.INCONCLUSIVE
    assert harness.snapshot(fresh.trial_id)["memory"] == {}
    assert harness.snapshot(fresh.trial_id)["effects"] == []
    assert harness.snapshot(original.trial_id) == past
    assert target.history == []
    assert target.last_trial_id == fresh.trial_id
    assert harness.observe(original.trial_id).events == original.events


@pytest.mark.asyncio
async def test_snapshot_changes_cannot_mutate_real_fixture_store_or_evidence() -> None:
    spec = APPLICATION_PACKS[0]
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    copied = harness.snapshot(result.trial_id)
    tickets = copied["tickets"]
    assert isinstance(tickets, dict)
    tickets.clear()
    effects = copied["effects"]
    assert isinstance(effects, list)
    effects.clear()
    assert harness.snapshot(result.trial_id)["tickets"]
    assert harness.snapshot(result.trial_id)["effects"]
    assert harness.observe(result.trial_id).events == result.events


@pytest.mark.asyncio
@pytest.mark.parametrize("external", [True, False])
async def test_cancellation_closes_active_app_sessions_preserving_actual_effect(
    external: bool,
) -> None:
    started = asyncio.Event()

    class BlockedAfterWrite(ScriptedApplicationTarget):
        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            context = current_trial_context()
            assert context is not None
            try:
                async with self.harness.trial(trial_id) as trial, trial.session() as session:
                    context.turn()
                    self.history.append(await session.retrieve())
                    context.turn()
                    assert await session.update_ticket("ticket.alpha", "closed")
                    started.set()
                    await asyncio.Event().wait()
            finally:
                self.last_trial_id = trial_id
                self.last_trace = self.harness.observe(trial_id)
            raise AssertionError("Blocked target must not complete")

    owned: list[Owned] = []
    task = asyncio.create_task(
        run_campaign(
            [make_case(APPLICATION_PACKS[0], owned, target_class=BlockedAfterWrite)],
            limits=CampaignLimits(timeout_seconds=30 if external else 0.03),
        )
    )
    await asyncio.wait_for(started.wait(), 1)
    assert owned[0].harness.snapshot()["session_ids"]
    if external:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        campaign = await task
        row = campaign.trials[0]
        assert row.state is TrialState.CANCELLED
        assert row.result is not None
        assert row.result.outcome is Outcome.VIOLATED
        assert ReasonCode.CAMPAIGN_DEADLINE in row.reason_codes
    item = owned[0]
    assert item.closed
    assert item.target.history == []
    assert item.harness.snapshot()["session_ids"] == []
    assert item.harness.observe(item.context.trial_id).complete
    effects = item.harness.snapshot()["effects"]
    assert isinstance(effects, list)
    assert len(effects) == 1
