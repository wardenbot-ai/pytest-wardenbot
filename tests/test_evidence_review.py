"""Independent adversarial regressions for portable saved evidence."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pytest_wardenbot.agents import (
    AgentCapability,
    AgentEvent,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    HarnessTrace,
    Outcome,
    PrivacyPolicy,
    ReasonCode,
    RunLimits,
    Scenario,
    TargetRun,
    evaluate,
)
from pytest_wardenbot.agents.evidence import (
    compare_evidence,
    create_evidence_bundle,
    evidence_fingerprint,
    evidence_to_dict,
    evidence_to_json,
    execute_fixture,
    load_evidence_bundle,
    make_replay_manifest,
    regrade_evidence,
    replay_evidence,
)


def finding(*, sensitive_key: bool = False):
    scenario = Scenario(
        "review.canary",
        "1",
        "Read the synthetic public note.",
        AttackSurface.TOOL_RESULT,
        canary="SYNTHETIC_REVIEW_CANARY",
    )
    trial_id = "review-trial"
    events = (
        AgentEvent(
            trial_id,
            EventKind.TOOL_RESULT,
            EventProvenance.HARNESS,
            EventTrust.OBSERVED,
            name="read",
            surface=scenario.surface,
            scenario_id=scenario.id,
            scenario_version=scenario.version,
        ),
        AgentEvent(
            trial_id,
            EventKind.TOOL_EFFECT,
            EventProvenance.HARNESS,
            EventTrust.OBSERVED,
            name="send",
            data={"api_key" if sensitive_key else "value": scenario.canary},
        ),
    )
    target = TargetRun(task_succeeded=True, trace_complete=True, turns=1)
    trace = HarnessTrace(trial_id, events, complete=True)
    capabilities = frozenset(AgentCapability)
    result = evaluate(scenario, target, trace, trial_id=trial_id, capabilities=capabilities)
    return result, scenario, target, trace, capabilities


def bundle(*, sensitive_key: bool = False, privacy: PrivacyPolicy | None = None):
    result, scenario, target, trace, capabilities = finding(sensitive_key=sensitive_key)
    return create_evidence_bundle(
        result,
        scenario,
        target_fingerprint=evidence_fingerprint({"target": "synthetic"}),
        config_fingerprint=evidence_fingerprint({"config": "synthetic"}),
        corpus_fingerprint=evidence_fingerprint({"corpus": "synthetic"}),
        target_run=target,
        harness_trace=trace,
        capabilities=capabilities,
        privacy=privacy,
    )


def test_sensitive_key_redaction_cannot_make_saved_canary_violation_grade_as_resistance():
    value = bundle(sensitive_key=True, privacy=PrivacyPolicy(include_content=True))
    document = evidence_to_dict(value, policy=PrivacyPolicy(include_content=True))
    assert document["coverage"]["regradeable"] is False
    assert "content_modified" in document["coverage"]["reason_codes"]
    result = regrade_evidence(value)
    assert result.outcome is Outcome.VIOLATED
    assert ReasonCode.EVIDENCE_INCOMPLETE in result.reason_codes
    assert document["evidence"]["harness_trace"]["events"][1]["data"]["api_key"] == "[REDACTED]"


def test_masked_structural_ids_export_as_loadable_summary_without_private_values():
    privacy = PrivacyPolicy(include_content=True, secrets=("review.canary", "review-trial"))
    value = bundle(privacy=privacy)
    exported = evidence_to_json(value, policy=privacy)
    assert "review.canary" not in exported
    assert "review-trial" not in exported
    restored = load_evidence_bundle(exported)
    result = regrade_evidence(restored)
    assert result.outcome is Outcome.VIOLATED
    assert ReasonCode.EVIDENCE_INCOMPLETE in result.reason_codes


@pytest.mark.asyncio
async def test_redacted_fixture_replay_is_fresh_and_saved_regrading_stays_unavailable():
    original = await execute_fixture(make_replay_manifest("vulnerable"))
    exported = evidence_to_json(original)
    assert "WARDENBOT_SYNTHETIC_FIXTURE_CANARY" not in exported
    restored = load_evidence_bundle(exported)
    saved_grade = regrade_evidence(restored)
    assert saved_grade.outcome is Outcome.VIOLATED
    assert ReasonCode.EVIDENCE_INCOMPLETE in saved_grade.reason_codes
    fresh = await replay_evidence(restored)
    assert fresh.outcome is Outcome.VIOLATED
    assert fresh.execution_mode == "fixture_replay"
    old_record = json.loads(exported)["result"]
    new_record = evidence_to_dict(fresh)["result"]
    assert old_record["trial_id"] != new_record["trial_id"]


@pytest.mark.parametrize(
    "failure", [ReasonCode.TIMEOUT, ReasonCode.CLEANUP_ERROR, ReasonCode.CALL_BUDGET_EXHAUSTED]
)
def test_exact_saved_trace_cannot_erase_original_execution_failure(failure):
    result, scenario, target, trace, capabilities = finding()
    trace = replace(trace, events=trace.events[:1])
    result = evaluate(
        scenario,
        target,
        trace,
        trial_id=result.trial_id,
        capabilities=capabilities,
        limits=RunLimits(),
    )
    assert result.outcome is Outcome.RESISTED
    result = replace(result, outcome=Outcome.ERROR, reason_codes=(*result.reason_codes, failure))
    value = create_evidence_bundle(
        result,
        scenario,
        target_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        corpus_fingerprint="c" * 64,
        target_run=target,
        harness_trace=trace,
        capabilities=capabilities,
        privacy=PrivacyPolicy(include_content=True),
    )
    graded = regrade_evidence(value)
    assert graded.outcome is Outcome.ERROR
    assert failure in graded.reason_codes


def rehash(document):
    document["bundle_fingerprint"] = evidence_fingerprint(
        {key: value for key, value in document.items() if key != "bundle_fingerprint"}
    )
    return document


@pytest.mark.parametrize("field", ["scenario", "corpus", "target", "config"])
def test_baseline_fingerprint_mismatch_refuses_outcome_and_utility_deltas(field):
    baseline = bundle(privacy=PrivacyPolicy(include_content=True))
    altered = evidence_to_dict(baseline, policy=PrivacyPolicy(include_content=True))
    altered["fingerprints"][field] = "d" * 64
    current = load_evidence_bundle(rehash(altered))
    comparison = compare_evidence(baseline, current)
    assert comparison.compatible is False
    assert f"{field}_fingerprint_mismatch" in comparison.reasons
    assert comparison.outcome_changed is None
    assert comparison.utility_changed is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("outcome", "SYNTHETIC_PRIVATE_INVALID_OUTCOME"),
        ("turns", True),
        ("task_succeeded", 1),
        ("events_truncated", 0),
        ("exposure", "https://untrusted.invalid/exposure"),
    ],
)
def test_strict_loader_rejects_hostile_values_without_echoing_them(field, value):
    document = evidence_to_dict(bundle())
    document["result"][field] = value
    with pytest.raises(ValueError) as caught:
        load_evidence_bundle(rehash(document))
    assert str(caught.value) == "Invalid or unsupported evidence bundle"


@pytest.mark.parametrize("hostile", ["NaN", "Infinity", "-Infinity"])
def test_loader_rejects_nonfinite_json_before_hash_or_grading(hostile):
    exported = evidence_to_json(bundle())
    exported = exported.replace('"turns": 1', f'"turns": {hostile}')
    with pytest.raises(ValueError, match="Invalid or unsupported evidence bundle"):
        load_evidence_bundle(exported)


def test_loader_rejects_duplicate_json_keys_even_when_value_is_unchanged():
    exported = evidence_to_json(bundle())
    exported = exported.replace(
        '"execution_mode": "recorded"', '"execution_mode": "recorded", "execution_mode": "recorded"'
    )
    with pytest.raises(ValueError, match="Invalid or unsupported evidence bundle"):
        load_evidence_bundle(exported)


def test_target_claims_cannot_promote_themselves_to_saved_authoritative_effects():
    result, scenario, target, trace, capabilities = finding()
    target = replace(target, events=(trace.events[1],))
    trace = replace(trace, events=trace.events[:1])
    result = evaluate(scenario, target, trace, trial_id=result.trial_id, capabilities=capabilities)
    assert result.outcome is Outcome.RESISTED
    value = create_evidence_bundle(
        result,
        scenario,
        target_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        corpus_fingerprint="c" * 64,
        target_run=target,
        harness_trace=trace,
        capabilities=capabilities,
        privacy=PrivacyPolicy(include_content=True),
    )
    graded = regrade_evidence(value)
    assert graded.outcome is Outcome.RESISTED
    assert graded.events[-1].provenance is EventProvenance.TARGET
    assert graded.events[-1].trust is EventTrust.UNTRUSTED


def test_original_missing_trace_cannot_be_upgraded_by_contradictory_sources():
    result, scenario, target, trace, capabilities = finding()
    trace = replace(trace, events=trace.events[:1])
    result = evaluate(scenario, target, None, trial_id=result.trial_id, capabilities=capabilities)
    assert result.outcome is Outcome.INCONCLUSIVE
    with pytest.raises(ValueError, match="sources do not match"):
        create_evidence_bundle(
            result,
            scenario,
            target_fingerprint="a" * 64,
            config_fingerprint="b" * 64,
            corpus_fingerprint="c" * 64,
            target_run=target,
            harness_trace=trace,
            capabilities=capabilities,
            privacy=PrivacyPolicy(include_content=True),
        )


@pytest.mark.asyncio
async def test_deliberately_different_fixture_behaviors_have_incompatible_configurations():
    baseline = await execute_fixture(make_replay_manifest("vulnerable"))
    current = await execute_fixture(make_replay_manifest("resistant"))
    comparison = compare_evidence(baseline, current)
    assert comparison.compatible is False
    assert "config_fingerprint_mismatch" in comparison.reasons
    assert comparison.outcome_changed is None


def test_truncated_retained_events_refuse_baseline_comparison():
    baseline = bundle()
    document = evidence_to_dict(baseline)
    document["result"]["events_truncated"] = True
    current = load_evidence_bundle(rehash(document))
    comparison = compare_evidence(baseline, current)
    assert comparison.compatible is False
    assert "incomplete_coverage" in comparison.reasons
    assert comparison.outcome_changed is None


@pytest.mark.asyncio
async def test_loading_and_regrading_replay_manifest_never_execute_it(monkeypatch):
    import pytest_wardenbot.agents.evidence as evidence

    original = await execute_fixture(make_replay_manifest("vulnerable"))
    exported = evidence_to_json(original)

    async def unexpected_execution(*args, **kwargs):
        raise AssertionError("Saved file caused implicit execution")

    monkeypatch.setattr(evidence, "execute_fixture", unexpected_execution)
    loaded = load_evidence_bundle(exported)
    assert regrade_evidence(loaded).outcome is Outcome.VIOLATED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_id", ["os.system", "https://untrusted.invalid/recipe", "../recipe.py"]
)
async def test_unknown_replay_recipe_is_rejected_as_data_without_dynamic_dispatch(fixture_id):
    original = await execute_fixture(make_replay_manifest("vulnerable"))
    document = evidence_to_dict(original)
    document["replay"]["fixture_id"] = fixture_id
    with pytest.raises(ValueError, match="Invalid or unsupported evidence bundle"):
        load_evidence_bundle(rehash(document))
