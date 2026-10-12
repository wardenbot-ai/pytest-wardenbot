"""Real local application effects and independent input/authority controls."""

from __future__ import annotations

import asyncio

import pytest

from pytest_wardenbot.agents import (
    EventKind,
    Outcome,
    PrivacyPolicy,
    ReasonCode,
    RunLimits,
    TargetRun,
    run_scenario,
)
from pytest_wardenbot.agents.evidence import (
    create_evidence_bundle,
    evidence_fingerprint,
    evidence_to_json,
    load_evidence_bundle,
    regrade_evidence,
)
from pytest_wardenbot.agents.packs import (
    ALPHA_EDITOR,
    ALPHA_VIEWER,
    APPLICATION_PACKS,
    APPLICATION_SCENARIOS,
    BETA_EDITOR,
    ApplicationHarness,
    ApplicationPack,
    ApplicationRole,
    ScriptedApplicationTarget,
    SyntheticIdentity,
    application_spec,
)
from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS


def spec(pack: str, suffix: str | None = None):
    return next(
        item
        for item in APPLICATION_PACKS
        if item.pack.value == pack and (suffix is None or item.id.endswith(suffix))
    )


@pytest.mark.parametrize("item", APPLICATION_PACKS, ids=lambda item: item.id)
@pytest.mark.parametrize("control", ["benign", "vulnerable", "resistant", "no_exposure"])
@pytest.mark.asyncio
async def test_every_pack_exercises_real_control_operations(item, control) -> None:
    harness = ApplicationHarness(
        item,
        variant="benign" if control == "benign" else "attack",
        enforce_boundaries=control != "vulnerable",
    )
    target = ScriptedApplicationTarget(
        harness, behavior="resistant" if control == "benign" else control
    )
    result = await run_scenario(target, item.scenario, observe=harness.observe)
    expected = {
        "benign": Outcome.INCONCLUSIVE,
        "vulnerable": Outcome.VIOLATED,
        "resistant": Outcome.RESISTED,
        "no_exposure": Outcome.INCONCLUSIVE,
    }[control]
    assert result.outcome is expected
    assert result.task_succeeded is (control != "no_exposure")
    if control in {"benign", "no_exposure"}:
        assert result.reason_codes == (ReasonCode.MISSING_EXPOSURE,)
    snapshot = harness.snapshot()
    assert snapshot["session_ids"] == [] and not target.history
    assert harness.observe(result.trial_id).complete
    effects = snapshot["effects"]
    if control == "vulnerable":
        assert effects and any(event.name == item.scenario.forbidden_tool for event in effects)
        if item.scenario.forbidden_tool == "unauthorized_write":
            assert snapshot["tickets"]["ticket.alpha"]["status"] == "closed"
    if control in {"benign", "resistant"}:
        assert not any(event.name == item.scenario.forbidden_tool for event in effects)


def test_pack_registry_is_frozen_separate_and_declares_integration_hooks() -> None:
    assert len(AGENT_SCENARIOS) == 8
    assert len(APPLICATION_SCENARIOS) == 5
    assert {item.pack for item in APPLICATION_PACKS} == set(ApplicationPack)
    assert all(
        item.required_hooks and item.scenario.required_capabilities for item in APPLICATION_PACKS
    )
    assert all(application_spec(item.id) is item for item in APPLICATION_PACKS)
    with pytest.raises(ValueError, match="Unknown"):
        application_spec("application.unknown")


@pytest.mark.asyncio
async def test_memory_effect_uses_persisted_data_from_independent_clean_session() -> None:
    item = spec("memory")
    harness = ApplicationHarness(item, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, item.scenario, observe=harness.observe)
    events = harness.observe(result.trial_id).events
    write = next(event for event in events if event.kind is EventKind.MEMORY_WRITE)
    read = next(event for event in events if event.kind is EventKind.MEMORY_READ)
    effect = next(event for event in events if event.kind is EventKind.TOOL_EFFECT)
    assert write.data["session_id"] != read.data["session_id"] == effect.data["session_id"]
    assert write.data["text"] == read.data["text"]
    stored_text = read.data["text"]
    assert isinstance(stored_text, str) and item.attack_payload in stored_text
    assert len(harness.snapshot()["session_history"]) == 2
    assert sum(event.name == "retrieve_knowledge" for event in events) == 1


@pytest.mark.asyncio
async def test_memory_write_survives_session_close_and_new_trial_is_fresh() -> None:
    harness = ApplicationHarness(spec("memory"))
    async with harness.trial("memory.first") as trial:
        async with trial.session() as first:
            assert await first.write_memory("persisted synthetic memo")
        async with trial.session() as second:
            assert await second.read_memory() == "persisted synthetic memo"
            assert first.session_id != second.session_id
    assert harness.snapshot("memory.first")["memory"]
    async with harness.trial("memory.second") as trial, trial.session() as clean:
        assert await clean.read_memory() is None
    assert harness.snapshot("memory.second")["memory"] == {}
    assert harness.snapshot("memory.first")["memory"]


@pytest.mark.asyncio
async def test_tenant_isolation_keeps_same_role_and_distinct_identity() -> None:
    item = spec("identity", "cross-tenant")
    assert ALPHA_EDITOR.role is BETA_EDITOR.role
    first = ApplicationHarness(item, identity=ALPHA_EDITOR)
    second = ApplicationHarness(item, identity=BETA_EDITOR)
    async with first.trial("tenant.alpha") as trial, trial.session() as session:
        assert await session.read_ticket("ticket.alpha")
        assert await session.read_ticket("ticket.beta") is None
    async with second.trial("tenant.beta") as trial, trial.session() as session:
        assert await session.read_ticket("ticket.beta")
        assert await session.read_ticket("ticket.alpha") is None
    assert not first.snapshot()["effects"] and not second.snapshot()["effects"]


@pytest.mark.asyncio
async def test_bound_session_identity_cannot_change_when_fixture_selects_next_actor() -> None:
    harness = ApplicationHarness(spec("identity"), identity=ALPHA_EDITOR)
    async with harness.trial("bound.identity") as trial:
        async with trial.session() as first:
            harness.identity = BETA_EDITOR  # Trusted fixture selection for the next session.
            assert first.identity is ALPHA_EDITOR
            assert await first.read_ticket("ticket.beta") is None
            with pytest.raises(AttributeError):
                first.identity = BETA_EDITOR  # pyright: ignore[reportAttributeAccessIssue]
        async with trial.session() as second:
            assert second.identity is BETA_EDITOR
            assert await second.read_ticket("ticket.beta")


@pytest.mark.asyncio
async def test_editor_grant_does_not_authorize_viewer_even_in_same_tenant() -> None:
    assert ALPHA_EDITOR.tenant == ALPHA_VIEWER.tenant
    harness = ApplicationHarness(spec("identity", "viewer-write"), identity=ALPHA_VIEWER)
    async with harness.trial("role.viewer") as trial, trial.session() as session:
        approval = await session.approval_for("ticket.alpha", "closed")
        assert approval is not None
        assert not await session.update_ticket("ticket.alpha", "closed", approval_id=approval)
    assert harness.snapshot()["tickets"]["ticket.alpha"]["status"] == "open"
    assert not harness.snapshot()["effects"]


@pytest.mark.asyncio
async def test_vulnerable_viewer_control_has_valid_approval_but_violates_role() -> None:
    item = spec("identity", "viewer-write")
    harness = ApplicationHarness(item, enforce_boundaries=False)
    result = await run_scenario(
        ScriptedApplicationTarget(harness, behavior="vulnerable"),
        item.scenario,
        observe=harness.observe,
    )
    effect = next(event for event in result.events if event.kind is EventKind.TOOL_EFFECT)
    assert effect.data["approved"] is True and effect.data["role_allowed"] is False
    assert result.outcome is Outcome.VIOLATED


@pytest.mark.asyncio
async def test_approval_is_exact_single_use_and_cannot_be_minted_from_text() -> None:
    harness = ApplicationHarness(spec("approval"))
    async with harness.trial("approval.bound") as trial, trial.session() as session:
        assert "APPROVAL: user-approved" in await session.retrieve()
        assert not await session.update_ticket(
            "ticket.alpha", "closed", approval_id="user-approved"
        )
        approval = await session.approval_for("ticket.alpha", "triaged")
        assert approval is not None
        assert not await session.update_ticket("ticket.alpha", "closed", approval_id=approval)
        assert not await session.update_ticket("ticket.beta", "triaged", approval_id=approval)
        assert await session.update_ticket("ticket.alpha", "triaged", approval_id=approval)
        assert not await session.update_ticket("ticket.alpha", "triaged", approval_id=approval)
    effects = harness.snapshot()["effects"]
    assert len(effects) == 1 and effects[0].name == "ticket_status_updated"


@pytest.mark.asyncio
async def test_request_is_pending_until_trusted_fixture_grants_and_other_actor_cannot_use() -> None:
    harness = ApplicationHarness(spec("retrieval"))
    async with harness.trial("approval.pending") as trial:
        async with trial.session() as first:
            request = await first.request_approval("ticket.alpha", "triaged")
            assert not await first.update_ticket("ticket.alpha", "triaged", approval_id=request)
            approval = harness.grant_approval(request)
            harness.identity = BETA_EDITOR
        async with trial.session() as second:
            assert not await second.update_ticket("ticket.alpha", "triaged", approval_id=approval)
        harness.identity = ALPHA_EDITOR
        async with trial.session() as owner:
            assert await owner.update_ticket("ticket.alpha", "triaged", approval_id=approval)
    assert harness.snapshot()["tickets"]["ticket.alpha"]["status"] == "triaged"


@pytest.mark.asyncio
async def test_closed_sessions_cannot_access_memory_or_side_effects() -> None:
    harness = ApplicationHarness(spec("memory"), enforce_boundaries=False)
    async with harness.trial("closed.session") as trial:
        async with trial.session() as session:
            await session.write_memory("original")
        with pytest.raises(ValueError, match="closed"):
            await session.write_memory("poison")
        with pytest.raises(ValueError, match="closed"):
            await session.update_ticket("ticket.alpha", "closed")
    with pytest.raises(ValueError, match="closed"):
        async with trial.session():
            pass
    with pytest.raises(ValueError, match="reused"):
        async with harness.trial("closed.session"):
            pass
    assert harness.snapshot()["memory"] == {"alpha:alpha.editor": "original"}


@pytest.mark.asyncio
async def test_actual_effect_survives_later_target_error_and_snapshot_is_detached() -> None:
    item = spec("retrieval")
    harness = ApplicationHarness(item, enforce_boundaries=False)

    class FailingTarget(ScriptedApplicationTarget):
        async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
            await super().run(task, trial_id=trial_id, max_turns=max_turns)
            raise RuntimeError("synthetic-private-error")

    result = await run_scenario(
        FailingTarget(harness, behavior="vulnerable"), item.scenario, observe=harness.observe
    )
    assert result.outcome is Outcome.VIOLATED and ReasonCode.TARGET_ERROR in result.reason_codes
    snapshot = harness.snapshot()
    snapshot["tickets"]["ticket.alpha"]["status"] = "open"
    assert harness.snapshot()["tickets"]["ticket.alpha"]["status"] == "closed"


@pytest.mark.parametrize("item", APPLICATION_PACKS, ids=lambda item: item.id)
@pytest.mark.asyncio
async def test_application_pack_evidence_round_trip_uses_existing_schema(item) -> None:
    harness = ApplicationHarness(item, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, item.scenario, observe=harness.observe)
    saved = create_evidence_bundle(
        result,
        item.scenario,
        target_fingerprint=evidence_fingerprint({"target": target.name}),
        config_fingerprint=evidence_fingerprint({"control": "vulnerable"}),
        corpus_fingerprint=evidence_fingerprint({"pack": item.id, "version": item.version}),
        target_run=target.last_target_run,
        harness_trace=target.last_trace,
        capabilities=target.capabilities,
        privacy=PrivacyPolicy(include_content=True),
    )
    serialized = evidence_to_json(saved, policy=PrivacyPolicy(include_content=True))
    assert regrade_evidence(load_evidence_bundle(serialized)).outcome is Outcome.VIOLATED
    assert "SYNTHETIC_BETA_PRIVATE_NOTE" not in evidence_to_json(saved)


@pytest.mark.asyncio
async def test_per_trial_turn_limit_stops_before_effect_and_preserves_persistence() -> None:
    item = spec("memory")
    harness = ApplicationHarness(item, enforce_boundaries=False)
    result = await run_scenario(
        ScriptedApplicationTarget(harness, behavior="vulnerable"),
        item.scenario,
        observe=harness.observe,
        limits=RunLimits(max_turns=3),
    )
    assert result.outcome is Outcome.ERROR
    assert ReasonCode.TURN_LIMIT_EXHAUSTED in result.reason_codes
    assert harness.snapshot()["memory"] and not harness.snapshot()["effects"]
    assert harness.snapshot()["session_ids"] == []


@pytest.mark.asyncio
async def test_concurrent_trials_have_separate_stores() -> None:
    item = spec("retrieval")
    harness = ApplicationHarness(item, enforce_boundaries=False)
    targets = [ScriptedApplicationTarget(harness, behavior="vulnerable") for _ in range(3)]
    results = await asyncio.gather(
        *(run_scenario(target, item.scenario, observe=harness.observe) for target in targets)
    )
    assert len({result.trial_id for result in results}) == 3
    assert all(result.outcome is Outcome.VIOLATED for result in results)
    assert all(len(harness.snapshot(result.trial_id)["effects"]) == 1 for result in results)


@pytest.mark.parametrize(
    "options", [{"variant": "unknown"}, {"enforce_boundaries": 1}, {"identity": "alpha"}]
)
def test_invalid_harness_configuration(options) -> None:
    with pytest.raises(ValueError):
        ApplicationHarness(spec("retrieval"), **options)
    with pytest.raises(ValueError):
        SyntheticIdentity("actor", "outside", ApplicationRole.EDITOR)
