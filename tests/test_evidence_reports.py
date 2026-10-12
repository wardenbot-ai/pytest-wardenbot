"""Portable views preserve outcome, coverage, privacy and inert evidence."""

from __future__ import annotations

from html.parser import HTMLParser
from xml.etree import ElementTree

import pytest

from pytest_wardenbot.agents import (
    AgentEvent,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    Exposure,
    Outcome,
    PrivacyPolicy,
    ReasonCode,
    RunResult,
    Scenario,
)
from pytest_wardenbot.agents.evidence import (
    EvidenceComparison,
    compare_evidence,
    create_evidence_bundle,
    evidence_fingerprint,
    execute_fixture,
    make_replay_manifest,
)
from pytest_wardenbot.agents.evidence_reports import evidence_to_junit, render_evidence_html


class _Document(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _properties(node: ElementTree.Element) -> dict[str, str]:
    return {
        child.attrib["name"]: child.attrib["value"] for child in node.findall("properties/property")
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior,tag",
    [("vulnerable", "failure"), ("resistant", None), ("no_exposure", "error")],
)
async def test_junit_security_outcomes_preserved(behavior, tag) -> None:
    bundle = await execute_fixture(make_replay_manifest(behavior))
    suite = ElementTree.fromstring(evidence_to_junit(bundle))
    cases = suite.findall("testcase")
    assert len(cases) == 2
    assert cases[0].attrib["name"].endswith(".security")
    assert cases[1].attrib["name"].endswith(".utility")
    properties = _properties(cases[0])
    assert properties["wardenbot.outcome"] == bundle.outcome.value
    assert properties["wardenbot.dimension"] == "security"
    assert properties["wardenbot.execution_mode"] == "fixture_execution"
    assert properties["wardenbot.bundle_fingerprint"]
    assert properties["wardenbot.grader_version"]
    assert "wardenbot.event_provenance" in properties
    status = [child.tag for child in cases[0] if child.tag != "properties"]
    assert status == ([tag] if tag else [])
    assert _properties(cases[1])["wardenbot.outcome"] == bundle.outcome.value


@pytest.mark.asyncio
async def test_inconclusive_is_skipped_only_when_coverage_optional() -> None:
    bundle = await execute_fixture(make_replay_manifest("no_exposure"))
    strict = ElementTree.fromstring(evidence_to_junit(bundle))
    optional = ElementTree.fromstring(evidence_to_junit(bundle, required=False))
    assert strict.find("testcase/error") is not None
    assert optional.find("testcase/skipped") is not None
    assert optional.attrib["tests"] == "2"


@pytest.mark.asyncio
async def test_sequence_counts_every_recorded_trial_and_utility() -> None:
    bundles = [
        await execute_fixture(make_replay_manifest(behavior))
        for behavior in ("resistant", "vulnerable", "no_exposure")
    ]
    suite = ElementTree.fromstring(evidence_to_junit(bundles))
    assert suite.attrib["tests"] == "6"
    assert len(suite.findall("testcase")) == 6
    assert (
        sum(
            _properties(case)["wardenbot.dimension"] == "security"
            for case in suite.findall("testcase")
        )
        == 3
    )
    html = render_evidence_html(bundles)
    assert html.count('<article class="trial">') == 3
    assert "Missing execution coverage" in html
    assert "Task utility" in html


@pytest.mark.parametrize("required,tag", [(True, "error"), (False, "skipped")])
def test_empty_input_keeps_explicit_missing_row(required: bool, tag: str) -> None:
    suite = ElementTree.fromstring(evidence_to_junit([], required=required))
    assert suite.attrib["tests"] == "1"
    assert suite.find(f"testcase/{tag}") is not None
    node = suite.find("testcase")
    assert node is not None
    assert _properties(node)["wardenbot.outcome"] == "not_run"
    assert "No trial evidence supplied" in render_evidence_html([])


@pytest.mark.asyncio
async def test_html_is_static_responsive_and_integrity_warnings_visible() -> None:
    bundle = await execute_fixture(make_replay_manifest("vulnerable"))
    rendered = render_evidence_html(bundle)
    parsed = _Document()
    parsed.feed(rendered)
    assert "script" not in parsed.tags
    assert not any(tag in parsed.tags for tag in ("iframe", "img", "link", "form"))
    assert not any(name.lower().startswith("on") for name, _ in parsed.attributes)
    assert not any(name in {"src", "href", "action"} for name, _ in parsed.attributes)
    assert ("http-equiv", "Content-Security-Policy") in parsed.attributes
    assert any(
        name == "content" and value and "default-src 'none'" in value
        for name, value in parsed.attributes
    )
    assert "@media(max-width:640px)" in rendered
    for label in (
        "Saved evidence is unauthenticated",
        "Offline regrading",
        "Evidence provenance / trust",
        "Bundle checksum",
        "Grader",
    ):
        assert label in rendered


@pytest.mark.asyncio
async def test_comparison_is_descriptive_and_keeps_utility_independent() -> None:
    bundle = await execute_fixture(make_replay_manifest("vulnerable"))
    comparison = compare_evidence(bundle, bundle)
    rendered = render_evidence_html(bundle, comparison=comparison)
    assert "Baseline comparison" in rendered
    assert "Baseline security" in rendered
    assert "Current task utility" in rendered
    suite = ElementTree.fromstring(evidence_to_junit(bundle, comparison=comparison))
    properties = _properties(suite)
    assert properties["wardenbot.comparison.compatible"] == "true"
    assert suite.find("testcase/failure") is not None


def test_reports_reject_unvalidated_values_without_printing_them() -> None:
    with pytest.raises(ValueError, match="validated EvidenceBundle"):
        render_evidence_html(["private-value"])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="required must be a bool"):
        evidence_to_junit([], required=1)  # type: ignore[arg-type]


def _bundle(
    outcome: Outcome = Outcome.RESISTED,
    utility: bool | None = True,
    *,
    events: tuple[AgentEvent, ...] = (),
    reasons: tuple[ReasonCode, ...] = (),
    config: str = "default",
    privacy: PrivacyPolicy | None = None,
):
    scenario = Scenario(
        "reports.private-label",
        "1",
        "Summarize the test document.",
        AttackSurface.TOOL_RESULT,
        forbidden_tool="test_write",
    )
    result = RunResult(
        "private-trial",
        scenario.id,
        scenario.version,
        outcome,
        Exposure.DELIVERED,
        task_succeeded=utility,
        events=events,
        reason_codes=reasons,
    )
    return create_evidence_bundle(
        result,
        scenario,
        target_fingerprint=evidence_fingerprint("target"),
        config_fingerprint=evidence_fingerprint(config),
        corpus_fingerprint=evidence_fingerprint("corpus"),
        privacy=privacy,
    )


@pytest.mark.parametrize("required,tag", [(True, "error"), (False, "skipped")])
def test_unknown_utility_is_explicit_and_security_remains_resisted(required, tag) -> None:
    suite = ElementTree.fromstring(evidence_to_junit(_bundle(utility=None), required=required))
    security, utility = suite.findall("testcase")
    assert security.find("failure") is None and security.find("error") is None
    assert utility.find(tag) is not None
    assert _properties(security)["wardenbot.outcome"] == "resisted"


def test_failed_utility_has_own_failure_without_relabeling_security() -> None:
    suite = ElementTree.fromstring(evidence_to_junit(_bundle(utility=False)))
    security, utility = suite.findall("testcase")
    assert security.find("failure") is None
    assert utility.find("failure") is not None
    assert suite.attrib["failures"] == "1"
    assert _properties(utility)["wardenbot.outcome"] == "resisted"


@pytest.mark.parametrize("outcome", [Outcome.ERROR, Outcome.UNSUPPORTED, Outcome.INCONCLUSIVE])
def test_error_or_unavailable_security_never_passes(outcome: Outcome) -> None:
    suite = ElementTree.fromstring(evidence_to_junit(_bundle(outcome)))
    assert suite.find("testcase/error") is not None
    assert _properties(suite.findall("testcase")[0])["wardenbot.outcome"] == outcome.value


def test_truncated_retained_events_visible_and_not_required_pass() -> None:
    event = AgentEvent("private-trial", EventKind.TOOL_RESULT)
    bundle = _bundle(events=(event,) * 1001)
    rendered = render_evidence_html(bundle)
    assert "Retained event coverage" in rendered
    assert "retained_events_truncated" in rendered
    suite = ElementTree.fromstring(evidence_to_junit(bundle))
    security = suite.findall("testcase")[0]
    assert security.find("error") is not None
    assert _properties(security)["wardenbot.retained_events_truncated"] == "true"


def test_hostile_opted_in_payload_remains_inert_and_literal_secret_filtered() -> None:
    payload = '</pre><script>alert("bad")</script><img src="https://invalid.test/leak">\x00'
    event = AgentEvent(
        "private-trial",
        EventKind.TOOL_RESULT,
        EventProvenance.HARNESS,
        EventTrust.OBSERVED,
        name=payload,
        data={"payload": payload, "secret": "private-token"},  # pragma: allowlist secret
    )
    bundle = _bundle(events=(event,), privacy=PrivacyPolicy(include_content=True))
    policy = PrivacyPolicy(include_content=True, secrets=("private-token", "private-trial"))
    rendered = render_evidence_html(bundle, policy=policy)
    parsed = _Document()
    parsed.feed(rendered)
    assert "script" not in parsed.tags
    assert "img" not in parsed.tags
    assert "&lt;script&gt;" in rendered
    assert "private-token" not in rendered
    assert "private-trial" not in rendered
    suite = ElementTree.fromstring(evidence_to_junit(bundle, policy=policy))
    assert "private-trial" not in ElementTree.tostring(suite, encoding="unicode")


def test_default_report_does_not_promote_retained_private_content() -> None:
    event = AgentEvent(
        "private-trial",
        EventKind.TOOL_RESULT,
        name="private-payload",
        data={"value": "private-payload"},
    )
    bundle = _bundle(events=(event,), privacy=PrivacyPolicy(include_content=True))
    assert "private-payload" not in render_evidence_html(bundle)
    assert "private-payload" not in evidence_to_junit(bundle)


def test_incompatible_baseline_report_refuses_delta_inference() -> None:
    current = _bundle(config="new")
    comparison = compare_evidence(_bundle(config="old"), current)
    rendered = render_evidence_html(current, comparison=comparison)
    assert "Comparison refused" in rendered
    assert "config_fingerprint_mismatch" in rendered
    assert "not assessed" in rendered
    properties = _properties(
        ElementTree.fromstring(evidence_to_junit(current, comparison=comparison))
    )
    assert properties["wardenbot.comparison.compatible"] == "false"


def test_baseline_text_escaped_xml_controls_replaced_and_secrets_filtered() -> None:
    comparison = EvidenceComparison(
        False,
        ('private-token\x00</dd><script>alert("bad")</script>',),
        Outcome.RESISTED,
        Outcome.VIOLATED,
        None,
        True,
        False,
        None,
    )
    policy = PrivacyPolicy(secrets=("private-token",))
    rendered = render_evidence_html(_bundle(), comparison=comparison, policy=policy)
    parsed = _Document()
    parsed.feed(rendered)
    assert "script" not in parsed.tags
    assert "&lt;script&gt;" in rendered
    assert "private-token" not in rendered
    xml = evidence_to_junit(_bundle(), comparison=comparison, policy=policy)
    suite = ElementTree.fromstring(xml)
    assert "private-token" not in xml
    assert "\x00" not in xml
    assert "wardenbot.comparison.reasons" in _properties(suite)
