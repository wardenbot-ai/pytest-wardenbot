"""Protect console/JSON/HTML outputs from recorded secrets and active markup."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents._privacy import PrivacyPolicy
from pytest_wardenbot.agents.contracts import (
    AgentEvent,
    EventKind,
    EventProvenance,
    EventTrust,
    Outcome,
    ReasonCode,
    RunResult,
)
from pytest_wardenbot.agents.reporting import (
    format_result,
    render_result_html,
    result_to_dict,
    result_to_json,
    to_legacy_attack_result,
)

SECRET = "synthetic-private-canary-for-tests"  # pragma: allowlist secret
HOSTILE = '</pre><script>alert("attack")</script><img src=x onerror=alert(1)>'


def finding() -> RunResult:
    event = AgentEvent(
        "trial-1",
        EventKind.TOOL_EFFECT,
        EventProvenance.HARNESS,
        EventTrust.OBSERVED,
        name=SECRET,
        data={
            "text": SECRET,
            "markup": HOSTILE,
            "api_key": "another-private-value",  # pragma: allowlist secret
        },
    )
    return RunResult(
        "trial-1",
        "test.control",
        "1",
        Outcome.VIOLATED,
        events=(event,),
        reason_codes=(ReasonCode.CANARY_LEAK,),
    )


@pytest.mark.parametrize("render", [repr, format_result, result_to_json, render_result_html])
def test_default_outputs_hide_payloads_and_names(render) -> None:
    rendered = render(finding())
    assert SECRET not in rendered
    assert "another-private-value" not in rendered
    assert HOSTILE not in rendered


def test_opt_in_literal_redaction_applies_to_every_output_field() -> None:
    result = replace(finding(), scenario_id=SECRET, trial_id=SECRET, usage={SECRET: 1})
    policy = PrivacyPolicy(include_content=True, secrets=(SECRET,))
    for render in (format_result, result_to_json, render_result_html):
        rendered = render(result, policy=policy)
        assert SECRET not in rendered
        assert "another-private-value" not in rendered
        assert "REDACTED" in rendered


def test_html_escapes_hostile_content_even_when_capture_opted_in() -> None:
    rendered = render_result_html(finding(), policy=PrivacyPolicy(include_content=True))
    assert "<script>" not in rendered
    assert "<img src" not in rendered
    assert "&lt;script&gt;" in rendered
    assert rendered.count("</pre>") == 1


def test_console_escapes_terminal_controls_in_structural_fields() -> None:
    result = replace(finding(), scenario_id="injected\n\x1b[31m")
    rendered = format_result(result)
    assert "\x1b" not in rendered
    assert "injected\\n\\u001b" in rendered


def test_exports_are_json_and_keep_outcome_and_task_success_separate() -> None:
    result = replace(finding(), task_succeeded=False)
    parsed = json.loads(result_to_json(result))
    assert parsed == result_to_dict(result)
    assert parsed["outcome"] == "violated"
    assert parsed["task_succeeded"] is False
    assert parsed["events"][0]["data"] == "[REDACTED]"


@pytest.mark.parametrize("outcome", [Outcome.INCONCLUSIVE, Outcome.UNSUPPORTED, Outcome.ERROR])
def test_unknown_outcomes_cannot_collapse_to_legacy_false(outcome: Outcome) -> None:
    with pytest.warns(DeprecationWarning), pytest.raises(WardenBotInfraError):
        to_legacy_attack_result(replace(finding(), outcome=outcome))


@pytest.mark.parametrize(
    "outcome, succeeded", [(Outcome.VIOLATED, True), (Outcome.RESISTED, False)]
)
def test_definite_legacy_conversion_is_explicit_and_sanitized(
    outcome: Outcome, succeeded: bool
) -> None:
    with pytest.warns(DeprecationWarning):
        result = to_legacy_attack_result(replace(finding(), outcome=outcome))
    assert result.succeeded is succeeded
    assert SECRET not in result.model_dump_json()
