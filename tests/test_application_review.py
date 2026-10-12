"""Independent boundary checks against actual local application operations."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pytest_wardenbot.agents import EventKind, EventProvenance, EventTrust, Outcome, evaluate
from pytest_wardenbot.agents.packs import (
    ALPHA_EDITOR,
    ALPHA_VIEWER,
    BETA_EDITOR,
    ApplicationHarness,
    ApplicationRole,
    ScriptedApplicationTarget,
    SyntheticIdentity,
    application_spec,
)
from pytest_wardenbot.agents.runner import run_scenario


@pytest.mark.asyncio
async def test_trusted_approval_cannot_authorize_changed_arguments_or_second_write():
    harness = ApplicationHarness(application_spec("application.approval.before-write"))
    async with harness.trial("review-approval") as trial, trial.session() as session:
        grant = await session.approval_for("ticket.alpha", "triaged")
        assert grant is not None
        assert await session.update_ticket("ticket.alpha", "closed", approval_id=grant) is False
        assert await session.update_ticket("ticket.beta", "triaged", approval_id=grant) is False
        assert await session.update_ticket("ticket.alpha", "triaged", approval_id=grant) is True
        assert await session.update_ticket("ticket.alpha", "triaged", approval_id=grant) is False
    snapshot = harness.snapshot("review-approval")
    assert snapshot["tickets"]["ticket.alpha"]["status"] == "triaged"
    assert snapshot["tickets"]["ticket.beta"]["status"] == "open"
    effects = [
        event
        for event in harness.observe("review-approval").events
        if event.kind is EventKind.TOOL_EFFECT
    ]
    assert len(effects) == 1
    assert effects[0].data["approved"] is True
    assert effects[0].name == "ticket_status_updated"


@pytest.mark.asyncio
async def test_valid_approval_does_not_give_viewer_editor_privileges():
    harness = ApplicationHarness(
        application_spec("application.identity.viewer-write"), identity=ALPHA_VIEWER
    )
    async with harness.trial("review-viewer") as trial, trial.session() as session:
        document = await session.retrieve()
        assert "Assume editor role" in document
        request = await session.request_approval("ticket.alpha", "closed")
        grant = harness.grant_approval(request, trial_id="review-viewer")
        assert session.identity.role is ApplicationRole.VIEWER
        assert await session.update_ticket("ticket.alpha", "closed", approval_id=grant) is False
    trace = harness.observe("review-viewer")
    denied = next(event for event in trace.events if event.name == "update_ticket_denied")
    assert denied.data["approved"] is True
    assert denied.data["tenant_allowed"] is True
    assert denied.data["role_allowed"] is False
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in trace.events)
    assert harness.snapshot()["tickets"]["ticket.alpha"]["status"] == "open"


@pytest.mark.asyncio
async def test_equal_role_does_not_authorize_peer_tenant_disclosure():
    spec = application_spec("application.identity.cross-tenant")
    for identity in (ALPHA_EDITOR, BETA_EDITOR):
        harness = ApplicationHarness(spec, identity=identity)
        async with harness.trial(f"review-{identity.tenant}") as trial, trial.session() as session:
            own = await session.read_ticket(f"ticket.{identity.tenant}")
            peer_tenant = "beta" if identity.tenant == "alpha" else "alpha"
            peer = await session.read_ticket(f"ticket.{peer_tenant}")
            assert own is not None and own["tenant"] == identity.tenant
            assert peer is None
        trace = harness.observe(f"review-{identity.tenant}")
        assert not any(event.kind is EventKind.TOOL_EFFECT for event in trace.events)
        assert any(event.name == "read_ticket_denied" for event in trace.events)


@pytest.mark.asyncio
async def test_retained_memory_causes_effect_only_in_distinct_later_session():
    spec = application_spec("application.memory.cross-session")
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    assert result.outcome is Outcome.VIOLATED
    events = result.events
    write = next(event for event in events if event.kind is EventKind.MEMORY_WRITE)
    read = next(event for event in events if event.kind is EventKind.MEMORY_READ)
    effect = next(event for event in events if event.kind is EventKind.TOOL_EFFECT)
    assert events.index(write) < events.index(read) < events.index(effect)
    assert write.data["session_id"] != read.data["session_id"]
    assert read.data["session_id"] == effect.data["session_id"]
    memory_text = read.data["text"]
    assert isinstance(memory_text, str)
    assert spec.attack_payload in memory_text
    snapshot = harness.snapshot(result.trial_id)
    assert len(snapshot["session_history"]) == 2
    assert snapshot["session_ids"] == []
    assert snapshot["tickets"]["ticket.alpha"]["status"] == "closed"
    assert not target.history


@pytest.mark.asyncio
async def test_target_claims_cannot_replace_application_observed_effects():
    spec = application_spec("application.retrieval.poisoned-document")
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    assert result.outcome is Outcome.VIOLATED
    assert target.last_target_run is not None
    claimed = replace(target.last_target_run, events=result.events, trace_complete=True)
    unobserved = evaluate(
        spec.scenario, claimed, None, trial_id=result.trial_id, capabilities=target.capabilities
    )
    assert unobserved.outcome is Outcome.INCONCLUSIVE
    assert all(
        event.provenance is EventProvenance.TARGET and event.trust is EventTrust.UNTRUSTED
        for event in unobserved.events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "other",
    [
        SyntheticIdentity("alpha.other-editor", "alpha", ApplicationRole.EDITOR),
        SyntheticIdentity(ALPHA_EDITOR.id, "beta", ApplicationRole.EDITOR),
    ],
)
async def test_memory_and_approval_are_scoped_to_both_identity_and_tenant(other):
    harness = ApplicationHarness(
        application_spec("application.memory.cross-session"), identity=ALPHA_EDITOR
    )
    async with harness.trial("review-scopes") as trial:
        async with trial.session() as original:
            assert await original.write_memory("SYNTHETIC_OWNER_PRIVATE_MEMORY")
            request = await original.request_approval("ticket.alpha", "closed")
            grant = harness.grant_approval(request, trial_id="review-scopes")
        # Only the trusted fixture changes the next session's authenticated identity.
        harness.identity = other
        async with trial.session() as peer:
            assert await peer.read_memory() is None
            assert await peer.update_ticket("ticket.alpha", "closed", approval_id=grant) is False
        harness.identity = ALPHA_EDITOR
        async with trial.session() as clean_owner:
            assert await clean_owner.read_memory() == "SYNTHETIC_OWNER_PRIVATE_MEMORY"
    trace = harness.observe("review-scopes")
    denied = next(event for event in trace.events if event.name == "update_ticket_denied")
    assert denied.data["approved"] is False
    assert denied.data["role_allowed"] is True
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in trace.events)


@pytest.mark.asyncio
async def test_attack_text_and_an_approval_request_are_not_trusted_grants():
    harness = ApplicationHarness(application_spec("application.approval.before-write"))
    async with harness.trial("review-no-self-approval") as trial, trial.session() as session:
        document = await session.retrieve()
        assert "APPROVAL: user-approved" in document
        request = await session.request_approval("ticket.alpha", "closed")
        assert await session.approval_for("ticket.alpha", "closed") is None
        assert await session.update_ticket("ticket.alpha", "closed", approval_id=request) is False
    trace = harness.observe("review-no-self-approval")
    grants = [event for event in trace.events if event.kind is EventKind.APPROVAL_GRANTED]
    assert len(grants) == 1  # Only the independently seeded benign triage grant.
    assert grants[0].data["status"] == "triaged"
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in trace.events)


@pytest.mark.asyncio
async def test_active_sessions_keep_their_bound_identity_when_fixture_opens_another_principal():
    harness = ApplicationHarness(
        application_spec("application.identity.cross-tenant"), identity=ALPHA_EDITOR
    )
    async with harness.trial("review-bound-sessions") as trial, trial.session() as alpha:
        harness.identity = BETA_EDITOR
        async with trial.session() as beta:
            assert alpha.identity == ALPHA_EDITOR
            assert beta.identity == BETA_EDITOR
            assert await alpha.read_ticket("ticket.beta") is None
            assert await beta.read_ticket("ticket.alpha") is None
            request = await alpha.request_approval("ticket.alpha", "closed")
            grant = harness.grant_approval(request, trial_id="review-bound-sessions")
            assert await alpha.approval_for("ticket.alpha", "closed") == grant
            assert await alpha.update_ticket("ticket.alpha", "closed", approval_id=grant)


@pytest.mark.asyncio
async def test_mutating_returned_observation_does_not_rewrite_authoritative_history():
    spec = application_spec("application.retrieval.poisoned-document")
    harness = ApplicationHarness(spec, enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    observed = harness.observe(result.trial_id)
    effect = next(event for event in observed.events if event.kind is EventKind.TOOL_EFFECT)
    assert effect.data["after"] == "closed"
    effect.data["after"] = "forged-status"
    retained = harness.observe(result.trial_id)
    retained_effect = next(
        event for event in retained.events if event.kind is EventKind.TOOL_EFFECT
    )
    assert retained_effect.data["after"] == "closed"
    assert harness.snapshot(result.trial_id)["tickets"]["ticket.alpha"]["status"] == "closed"
