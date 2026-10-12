"""Inert, standalone HTML and JUnit views of portable agent evidence."""

from __future__ import annotations

import html
import json
from collections import Counter
from collections.abc import Sequence
from typing import Any
from xml.etree import ElementTree

from pytest_wardenbot.agents._privacy import PrivacyPolicy, redact_text
from pytest_wardenbot.agents.contracts import ReasonCode
from pytest_wardenbot.agents.evidence import (
    EvidenceBundle,
    EvidenceComparison,
    comparison_to_dict,
    evidence_to_dict,
)

_STYLE = """
:root{color-scheme:light;--ink:#172d3e;--muted:#526474;--line:#d9e1e5;
--paper:#f6f5f0;--card:#fff;--green:#236350;--red:#a03444;--amber:#8a5813}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);
font:15px/1.55 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:44px 28px 60px}h1,h2,h3,p{margin:0}
h1{font-size:clamp(28px,5vw,46px);line-height:1.15;letter-spacing:-.035em;
margin:10px 0 14px}h2{font-size:22px;letter-spacing:-.015em;margin-bottom:12px}
h3{font-size:17px;overflow-wrap:anywhere}.eyebrow{font-size:11px;letter-spacing:.14em;
font-weight:750;text-transform:uppercase;color:var(--green)}.intro{max-width:760px;
color:var(--muted)}.notice{margin-top:20px;border-left:3px solid var(--amber);
background:#fff3de;padding:12px 16px;color:#654810;font-size:13px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:26px 0}
.stat,.panel,.trial{background:var(--card);border:1px solid var(--line);border-radius:12px}
.stat{padding:16px 20px}.stat strong{display:block;font-size:32px;line-height:1.15}
.stat span{font-size:12px;color:var(--muted)}.panel{padding:22px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}.small{font-size:12px;color:var(--muted)}
dl{display:grid;grid-template-columns:minmax(110px,auto) 1fr;gap:7px 16px;margin:0}
dt{font-size:12px;color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
.trials{display:grid;gap:14px}.trial{padding:20px}.trial-head{display:flex;gap:12px;
justify-content:space-between;align-items:flex-start;margin-bottom:14px}
.badge{display:inline-block;flex-shrink:0;border:1px solid var(--line);border-radius:100px;
padding:4px 11px;font-size:11px;text-transform:uppercase;font-weight:700}
.badge.resisted{color:var(--green);background:#e9f4ee;border-color:#c5dfd1}
.badge.violated{color:var(--red);background:#fbecef;border-color:#efcbd2}
.badge.error,.badge.cancelled{color:var(--amber);background:#fff3de;border-color:#ead7b5}
.badge.inconclusive,.badge.unsupported,.badge.not_run{color:var(--muted);background:#eef2f4}
.reasons{margin-top:12px;font-size:12px;color:var(--muted);overflow-wrap:anywhere}
details{margin-top:16px;border-top:1px solid var(--line);padding-top:12px}
summary{cursor:pointer;font-size:12px;font-weight:650}pre{white-space:pre-wrap;
overflow-wrap:anywhere;font:12px/1.6 ui-monospace,SFMono-Regular,monospace;
background:#f2f5f6;border-radius:8px;padding:16px;margin:12px 0 0;max-height:420px;overflow:auto}
.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);
vertical-align:top;overflow-wrap:anywhere}th{color:var(--muted);font-size:11px;text-transform:uppercase}
footer{margin-top:30px;border-top:1px solid var(--line);padding-top:16px;
color:var(--muted);font-size:12px}
@media(max-width:640px){main{padding:28px 16px 40px}.stats{grid-template-columns:1fr 1fr;
gap:8px}.stat{padding:14px}.stat strong{font-size:28px}.grid{grid-template-columns:1fr;gap:0}
.panel,.trial{padding:16px}.trial-head{flex-direction:column}dl{grid-template-columns:1fr;gap:2px}
dd{margin-bottom:8px}th,td{padding:8px}.notice{padding:10px 12px}}
@media print{body{background:#fff}main{max-width:none;padding:0}details{break-inside:avoid}
.trial,.panel{break-inside:avoid}pre{max-height:none}.notice{background:#fff}}
"""


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False)


def _xml_text(value: object) -> str:
    """Replace XML 1.0 forbidden controls in every caller-supplied attribute."""
    return "".join(
        char
        if char in "\t\n\r"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
        else "\ufffd"
        for char in str(value)
    )


def _property(parent: ElementTree.Element, name: str, value: object) -> None:
    ElementTree.SubElement(parent, "property", name=_xml_text(name), value=_xml_text(value))


def _definition(items: list[tuple[str, object]]) -> str:
    return (
        "<dl>"
        + "".join(f"<dt>{_escape(label)}</dt><dd>{_escape(value)}</dd>" for label, value in items)
        + "</dl>"
    )


def _documents(
    bundles: EvidenceBundle | Sequence[EvidenceBundle], policy: PrivacyPolicy | None
) -> list[dict[str, Any]]:
    values = [bundles] if isinstance(bundles, EvidenceBundle) else list(bundles)
    if any(not isinstance(bundle, EvidenceBundle) for bundle in values):
        raise ValueError("Evidence reports require validated EvidenceBundle objects")
    return [evidence_to_dict(bundle, policy=policy) for bundle in values]


def _utility(value: object) -> str:
    return "succeeded" if value is True else "failed" if value is False else "unknown"


def _outcome(document: dict[str, Any]) -> str:
    return str(document["result"]["outcome"])


def _missing(document: dict[str, Any]) -> list[str]:
    result = document["result"]
    unavailable = {
        reason.value
        for reason in ReasonCode
        if reason
        not in {ReasonCode.BOUNDARY_HELD, ReasonCode.FORBIDDEN_TOOL_EFFECT, ReasonCode.CANARY_LEAK}
    }
    reasons = [str(reason) for reason in result["reason_codes"] if reason in unavailable]
    if result.get("events_truncated", False):
        reasons.append("retained_events_truncated")
    if _outcome(document) == "resisted" and result["exposure"] == "not_observed":
        reasons.append("missing_exposure")
    if _outcome(document) not in {"violated", "resisted"}:
        reasons = list(dict.fromkeys([_outcome(document), *reasons]))
    return reasons


def _fingerprints(document: dict[str, Any]) -> str:
    return _definition(
        [
            ("Bundle checksum", document["bundle_fingerprint"]),
            ("Grader", document["grader_version"]),
            *[
                (f"{name.capitalize()} fingerprint", value)
                for name, value in document["fingerprints"].items()
            ],
        ]
    )


def _trial_html(document: dict[str, Any], index: int) -> str:
    result = document["result"]
    coverage = document["coverage"]
    outcome = _outcome(document)
    events = result["events"]
    provenance = Counter(f"{event['provenance']} / {event['trust']}" for event in events)
    provenance_text = ", ".join(f"{label}: {count}" for label, count in sorted(provenance.items()))
    missing = _missing(document)
    reason_text = _escape(", ".join(result["reason_codes"]) or "none declared")
    return (
        '<article class="trial">'
        '<div class="trial-head"><div><p class="eyebrow">'
        f"Trial {index}</p><h3>{_escape(result['scenario_id'])}"
        f' <span class="small">@{_escape(result["scenario_version"])}</span></h3></div>'
        f'<span class="badge {_escape(outcome)}">{_escape(outcome)}</span></div>'
        + _definition(
            [
                ("Task utility", _utility(result["task_succeeded"])),
                ("Exposure", result["exposure"]),
                ("Trial ID", result["trial_id"]),
                ("Missing execution coverage", ", ".join(missing) or "none declared"),
                ("Evidence provenance / trust", provenance_text or "no events recorded"),
                (
                    "Retained event coverage",
                    "truncated"
                    if result.get("events_truncated", False)
                    else "not marked truncated",
                ),
                ("Offline regrading", "available" if coverage["regradeable"] else "unavailable"),
                ("Regrading limitations", ", ".join(coverage["reason_codes"]) or "none declared"),
                ("Execution mode", document.get("execution_mode", "recorded evidence")),
            ]
        )
        + f'<p class="reasons">Reasons: {reason_text}</p>'
        + "<details><summary>Fingerprints and grader</summary>"
        + _fingerprints(document)
        + "</details>"
        + "<details><summary>Sanitized evidence and observations</summary>"
        + f"<pre>{_escape(_json({'events': events, 'evidence': document['evidence']}))}</pre>"
        + "</details></article>"
    )


def _comparison_dict(
    comparison: EvidenceComparison, policy: PrivacyPolicy | None
) -> dict[str, Any]:
    data = comparison_to_dict(comparison)
    privacy = policy or PrivacyPolicy()
    data["reasons"] = [redact_text(reason, policy=privacy) for reason in data["reasons"]]
    return data


def _comparison_html(comparison: EvidenceComparison | None, policy: PrivacyPolicy | None) -> str:
    if comparison is None:
        return ""
    data = _comparison_dict(comparison, policy)
    compatible = data["compatible"]
    state = "Comparable metadata" if compatible else "Comparison refused"
    return (
        '<section class="panel"><h2>Baseline comparison</h2>'
        + _definition(
            [
                ("Compatibility", state),
                ("Reasons", ", ".join(data["reasons"]) or "none declared"),
                ("Baseline security", data["baseline_outcome"]),
                ("Current security", data["current_outcome"]),
                (
                    "Security changed",
                    ("yes" if data["outcome_changed"] else "no") if compatible else "not assessed",
                ),
                ("Baseline task utility", _utility(data["baseline_task_succeeded"])),
                ("Current task utility", _utility(data["current_task_succeeded"])),
                (
                    "Utility changed",
                    (
                        "unknown"
                        if data["utility_changed"] is None
                        else "yes"
                        if data["utility_changed"]
                        else "no"
                    )
                    if compatible
                    else "not assessed",
                ),
            ]
        )
        + '<p class="small">A compatible comparison describes these observations. '
        "It does not establish causality or a model-wide improvement.</p></section>"
    )


def render_evidence_html(
    bundle: EvidenceBundle | Sequence[EvidenceBundle],
    *,
    comparison: EvidenceComparison | None = None,
    policy: PrivacyPolicy | None = None,
) -> str:
    """Render validated evidence as escaped static HTML without external assets.

    This function performs no model calls, replay, or regrading. Execution
    outcomes, task utility and unavailable coverage are shown independently.
    """
    documents = _documents(bundle, policy)
    outcomes = Counter(_outcome(document) for document in documents)
    utility = Counter(_utility(document["result"]["task_succeeded"]) for document in documents)
    unavailable = sum(bool(_missing(document)) for document in documents)
    stats = [
        (len(documents), "recorded trials"),
        (outcomes["violated"], "observed violations"),
        (outcomes["resisted"], "recorded resistance"),
        (unavailable or int(not documents), "unavailable coverage rows"),
    ]
    empty = (
        '<article class="trial"><h3>No trial evidence supplied</h3>'
        "<p>No execution is recorded. This is missing coverage "
        "and cannot establish a pass.</p></article>"
        if not documents
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src &#39;none&#39;; '
        'style-src &#39;unsafe-inline&#39;; base-uri &#39;none&#39;; form-action &#39;none&#39;">'
        '<meta name="referrer" content="no-referrer">'
        "<title>WardenBot evidence bundle</title>"
        f"<style>{_STYLE}</style></head><body><main>"
        '<header><p class="eyebrow">WardenBot / portable evidence</p>'
        "<h1>Every observation,<br>with its limits visible.</h1>"
        '<p class="intro">Recorded security outcomes, task utility and missing coverage '
        "are independent. This view renders evidence; it performs no new execution.</p>"
        '<p class="notice">Saved evidence is unauthenticated. Checksums identify content '
        "and detect accidental changes; they do not prove who produced a trace or that "
        "a saved claim is true. A recorded resistance outcome "
        "is not a fresh safety check.</p></header>"
        '<section class="stats" aria-label="Security and coverage summary">'
        + "".join(
            f'<div class="stat"><strong>{count}</strong><span>{_escape(label)}</span></div>'
            for count, label in stats
        )
        + '</section><div class="grid"><section class="panel"><h2>Task utility</h2>'
        + _definition(
            [
                ("Succeeded", utility["succeeded"]),
                ("Failed", utility["failed"]),
                ("Unknown", utility["unknown"]),
            ]
        )
        + '<p class="small">Utility checks retain their original meaning; '
        "fact presence is not semantic correctness.</p></section>"
        '<section class="panel"><h2>Coverage boundary</h2><p class="small">'
        "Evidence describes only the instrumented boundary and declared scenario. "
        "Omitted content can prevent offline regrading even when an original run completed. "
        "Missing execution never counts as resistance.</p></section></div>"
        + _comparison_html(comparison, policy)
        + '<section aria-label="Recorded trials" class="trials">'
        + "".join(_trial_html(document, index) for index, document in enumerate(documents, 1))
        + empty
        + "</section><footer>Content is hidden by default. Explicit content capture "
        "can still contain private data; use configured redaction and review before sharing. "
        "Offline regrading evaluates saved observations. Fixture replay or a live rerun "
        "requires separate explicit execution and may produce a different result.</footer>"
        "</main></body></html>"
    )


def evidence_to_junit(
    bundle: EvidenceBundle | Sequence[EvidenceBundle],
    *,
    required: bool = True,
    comparison: EvidenceComparison | None = None,
    policy: PrivacyPolicy | None = None,
) -> str:
    """Export security and task utility as separate, explicit JUnit test cases.

    Required coverage maps unavailable evidence/unknown utility to errors;
    optional coverage maps them to skips. Nothing unavailable becomes a pass.
    """
    if not isinstance(required, bool):
        raise ValueError("required must be a bool")
    documents = _documents(bundle, policy)
    suite = ElementTree.Element("testsuite", name="wardenbot.evidence")
    suite_properties = ElementTree.SubElement(suite, "properties")
    _property(suite_properties, "wardenbot.source", "saved_evidence_no_new_execution")
    _property(suite_properties, "wardenbot.fingerprint_authentication", "none")
    _property(suite_properties, "wardenbot.required_coverage", str(required).lower())
    if comparison is not None:
        for key, value in _comparison_dict(comparison, policy).items():
            _property(suite_properties, f"wardenbot.comparison.{key}", _json(value))
    counters = Counter()

    def mark(node: ElementTree.Element, tag: str, kind: str, message: str) -> None:
        ElementTree.SubElement(node, tag, type=kind, message=_xml_text(message))
        counters[tag] += 1

    for index, document in enumerate(documents, 1):
        result = document["result"]
        name = f"{index}.{result['scenario_id']}@{result['scenario_version']}"
        for dimension in ("security", "utility"):
            node = ElementTree.SubElement(
                suite,
                "testcase",
                classname="wardenbot.evidence",
                name=_xml_text(f"{name}.{dimension}"),
            )
            properties = ElementTree.SubElement(node, "properties")
            for key, value in {
                "dimension": dimension,
                "trial_id": result["trial_id"],
                "scenario_id": result["scenario_id"],
                "scenario_version": result["scenario_version"],
                "outcome": result["outcome"],
                "exposure": result["exposure"],
                "task_succeeded": _utility(result["task_succeeded"]),
                "reason_codes": _json(result["reason_codes"]),
                "grader_version": document["grader_version"],
                "bundle_fingerprint": document["bundle_fingerprint"],
                "fingerprints": _json(document["fingerprints"]),
                "offline_regradeable": str(document["coverage"]["regradeable"]).lower(),
                "execution_mode": document.get("execution_mode", "recorded evidence"),
                "missing_execution_coverage": _json(_missing(document)),
                "retained_events_truncated": str(result.get("events_truncated", False)).lower(),
                "event_provenance": _json(
                    dict(Counter(event["provenance"] for event in result["events"]))
                ),
            }.items():
                _property(properties, f"wardenbot.{key}", value)
            if dimension == "utility":
                if result["task_succeeded"] is False:
                    mark(node, "failure", "TaskUtilityFailure", "Recorded task utility failed")
                elif result["task_succeeded"] is not True:
                    mark(
                        node,
                        "error" if required else "skipped",
                        "MissingTaskUtility",
                        "Task utility is unknown; no pass is established",
                    )
            elif result["outcome"] == "violated":
                mark(
                    node,
                    "failure",
                    "ObservedBoundaryViolation",
                    "Recorded forbidden effect or canary disclosure",
                )
            elif result["outcome"] == "error":
                mark(node, "error", "TrialInfrastructureError", "Recorded trial execution error")
            elif result["outcome"] != "resisted" or _missing(document):
                mark(
                    node,
                    "error" if required else "skipped",
                    "MissingSecurityCoverage",
                    "Recorded evidence cannot establish observed resistance",
                )
    if not documents:
        node = ElementTree.SubElement(
            suite, "testcase", classname="wardenbot.evidence", name="not_run.security"
        )
        properties = ElementTree.SubElement(node, "properties")
        _property(properties, "wardenbot.outcome", "not_run")
        mark(
            node,
            "error" if required else "skipped",
            "NoTrialEvidence",
            "No recorded trial evidence supplied",
        )
    suite.set("tests", str(len(suite.findall("testcase"))))
    for tag, attribute in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
        suite.set(attribute, str(counters[tag]))
    return ElementTree.tostring(suite, encoding="unicode", xml_declaration=True)
