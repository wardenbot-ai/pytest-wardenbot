"""Content-minimized output for agent trials, with explicit legacy conversion.

These are small diagnostic exports. The evidence module provides portable,
versioned scenario bundles and offline re-grading. Use these functions instead
of dataclasses.asdict, which exposes payloads without a privacy boundary.
"""

from __future__ import annotations

import html
import json
import warnings
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents._privacy import PrivacyPolicy, redact_text, safe_content
from pytest_wardenbot.agents.contracts import Outcome, RunResult
from pytest_wardenbot.runners.base import AttackResult


def result_to_dict(result: RunResult, *, policy: PrivacyPolicy | None = None) -> dict[str, Any]:
    """Export bounded diagnostics with free-text evidence hidden by default.

    IDs are user-chosen structural labels; do not put credentials in them.
    ``policy.secrets`` also filters these labels. Capturing evidence content is
    explicit opt-in and best-effort: known values and sensitive keys are masked,
    but arbitrary unrecognized personal information cannot be inferred.
    """
    policy = policy or PrivacyPolicy()
    return {
        "schema_version": "1",
        "trial_id": redact_text(result.trial_id, policy=policy),
        "scenario_id": redact_text(result.scenario_id, policy=policy),
        "scenario_version": redact_text(result.scenario_version, policy=policy),
        "outcome": result.outcome.value,
        "exposure": result.exposure.value,
        "task_succeeded": result.task_succeeded,
        "reason_codes": [reason.value for reason in result.reason_codes],
        "turns": result.turns,
        "limits": {
            "timeout_seconds": result.limits.timeout_seconds,
            "max_turns": result.limits.max_turns,
            "cleanup_timeout_seconds": result.limits.cleanup_timeout_seconds,
        },
        "usage": safe_content(result.usage, policy=policy),
        "events": [
            {
                "kind": event.kind.value,
                "provenance": event.provenance.value,
                "trust": event.trust.value,
                "surface": event.surface.value if event.surface is not None else None,
                "scenario_id": (
                    redact_text(event.scenario_id, policy=policy)
                    if event.scenario_id is not None
                    else None
                ),
                "scenario_version": (
                    redact_text(event.scenario_version, policy=policy)
                    if event.scenario_version is not None
                    else None
                ),
                "name": safe_content(event.name, policy=policy),
                "data": safe_content(event.data, policy=policy),
            }
            for event in result.events[:1000]
        ],
        "events_truncated": len(result.events) > 1000,
    }


def result_to_json(result: RunResult, *, policy: PrivacyPolicy | None = None) -> str:
    """Return JSON with identical privacy defaults to console and HTML output."""
    return json.dumps(
        result_to_dict(result, policy=policy), ensure_ascii=True, indent=2, allow_nan=False
    )


def format_result(result: RunResult, *, policy: PrivacyPolicy | None = None) -> str:
    """Format diagnostics for a pytest assertion without raw exception chains."""
    return "WardenBot agent trial\n" + result_to_json(result, policy=policy)


def render_result_html(result: RunResult, *, policy: PrivacyPolicy | None = None) -> str:
    """Render inert, escaped diagnostic HTML without scripts or external assets."""
    body = html.escape(result_to_json(result, policy=policy), quote=True)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>WardenBot agent trial</title>"
        "<style>body{font:16px system-ui;max-width:960px;margin:32px auto;padding:0 20px}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f3;padding:20px}"
        "</style></head><body><h1>WardenBot agent trial</h1>"
        "<p>Security outcome and task success are separate. "
        "Evidence covers only the declared instrumented boundary.</p>"
        f"<pre>{body}</pre></body></html>"
    )


def to_legacy_attack_result(result: RunResult) -> AttackResult:
    """Convert definite outcomes only; incomplete coverage must never be False.

    Existing AttackResult construction/imports remain compatible. New agent
    integrations should consume RunResult directly; this explicit, deprecated
    bridge exists for callers migrating a legacy boolean result consumer.
    """
    warnings.warn(
        "Boolean attack results lose agent evidence; consume RunResult.outcome instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    if result.outcome not in {Outcome.VIOLATED, Outcome.RESISTED}:
        raise WardenBotInfraError(
            "An incomplete agent trial cannot be converted to a boolean attack result."
        ) from None
    return AttackResult(
        succeeded=result.outcome is Outcome.VIOLATED,
        summary=f"Observed agent outcome: {result.outcome.value}",
        details=result_to_dict(result),
    )
