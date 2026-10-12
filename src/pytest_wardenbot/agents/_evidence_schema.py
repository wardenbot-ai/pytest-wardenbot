"""Strict, bounded JSON schema for inert portable evidence (no object imports)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, NoReturn

from pytest_wardenbot.agents.contracts import (
    AgentCapability,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    Exposure,
    Outcome,
    ReasonCode,
    RunLimits,
)

SCHEMA_VERSION = "1"
GRADER_VERSION = "agent-boundary-1"
MAX_BYTES = 2_000_000
MAX_EVENTS = 1000


def fail() -> NoReturn:
    raise ValueError("Invalid or unsupported evidence bundle")


def canonical(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError, OverflowError, RecursionError):
        fail()


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def digest(value: object) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        fail()


def keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        fail()


def text(value: Any, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not isinstance(value, str) or len(value) > 100_000:
        fail()


def boolean(value: object, *, optional: bool = False) -> None:
    if not isinstance(value, bool) and not (optional and value is None):
        fail()


def integer(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        fail()


def enum_value(value: Any, enum: Any, *, optional: bool = False) -> None:
    if value is None and optional:
        return
    try:
        enum(value)
    except (ValueError, TypeError):
        fail()


def enums(value: Any, enum: Any) -> None:
    if not isinstance(value, list) or len(value) > 100 or len(value) != len(set(value)):
        fail()
    for item in value:
        enum_value(item, enum)


def usage(value: Any, *, redacted: bool = False) -> None:
    if value is None or (redacted and value == "[REDACTED]"):
        return
    if not isinstance(value, dict) or len(value) > 1000:
        fail()
    for key, item in value.items():
        text(key)
        if isinstance(item, bool) or not isinstance(item, int | float) or item < 0:
            fail()
        if isinstance(item, float) and not math.isfinite(item):
            fail()


def event(value: Any, *, diagnostic: bool = False) -> None:
    expected = {
        "kind",
        "provenance",
        "trust",
        "surface",
        "scenario_id",
        "scenario_version",
        "name",
        "data",
    }
    if not diagnostic:
        expected.add("trial_id")
    keys(value, expected)
    if not diagnostic:
        text(value["trial_id"])
    enum_value(value["kind"], EventKind)
    enum_value(value["provenance"], EventProvenance)
    enum_value(value["trust"], EventTrust)
    enum_value(value["surface"], AttackSurface, optional=True)
    for label in ("scenario_id", "scenario_version"):
        text(value[label], optional=True)
    text(value["name"])
    if not isinstance(value["data"], dict) and value["data"] != "[REDACTED]":
        fail()


def events(value: Any, *, diagnostic: bool = False) -> None:
    if not isinstance(value, list) or len(value) > MAX_EVENTS:
        fail()
    for item in value:
        event(item, diagnostic=diagnostic)


def scenario(value: Any) -> None:
    keys(
        value,
        {
            "id",
            "version",
            "task",
            "surface",
            "required_capabilities",
            "forbidden_tool",
            "canary",
            "require_processing",
        },
    )
    text(value["id"])
    text(value["version"])
    text(value["task"])
    enum_value(value["surface"], AttackSurface)
    enums(value["required_capabilities"], AgentCapability)
    text(value["forbidden_tool"], optional=True)
    text(value["canary"], optional=True)
    if value["forbidden_tool"] is None and value["canary"] is None:
        fail()
    boolean(value["require_processing"])


def result(value: Any) -> None:
    keys(
        value,
        {
            "schema_version",
            "trial_id",
            "scenario_id",
            "scenario_version",
            "outcome",
            "exposure",
            "task_succeeded",
            "reason_codes",
            "turns",
            "limits",
            "usage",
            "events",
            "events_truncated",
        },
    )
    if value["schema_version"] != "1":
        fail()
    for label in ("trial_id", "scenario_id", "scenario_version"):
        text(value[label])
    enum_value(value["outcome"], Outcome)
    enum_value(value["exposure"], Exposure)
    boolean(value["task_succeeded"], optional=True)
    enums(value["reason_codes"], ReasonCode)
    integer(value["turns"])
    keys(value["limits"], {"timeout_seconds", "max_turns", "cleanup_timeout_seconds"})
    try:
        RunLimits(**value["limits"])
    except (ValueError, TypeError, OverflowError):
        fail()
    usage(value["usage"], redacted=True)
    events(value["events"], diagnostic=True)
    boolean(value["events_truncated"])


def raw_evidence(value: Any) -> None:
    if value is None:
        return
    keys(value, {"capabilities", "target_run", "harness_trace"})
    enums(value["capabilities"], AgentCapability)
    target = value["target_run"]
    keys(
        target,
        {
            "events",
            "task_succeeded",
            "trace_complete",
            "turns",
            "final_text",
            "usage",
            "limit_exhausted",
        },
    )
    events(target["events"])
    boolean(target["task_succeeded"], optional=True)
    boolean(target["trace_complete"])
    boolean(target["limit_exhausted"])
    integer(target["turns"])
    text(target["final_text"])
    usage(target["usage"], redacted=True)
    trace = value["harness_trace"]
    if trace is not None:
        keys(trace, {"trial_id", "events", "complete"})
        text(trace["trial_id"])
        events(trace["events"])
        boolean(trace["complete"])
        for item in trace["events"]:
            if item["provenance"] != "harness" or item["trust"] != "observed":
                fail()


def replay(value: Any) -> None:
    if value is None:
        return
    keys(
        value,
        {
            "fixture_id",
            "fixture_version",
            "behavior",
            "scenario_fingerprint",
            "corpus_fingerprint",
            "expected_outcome",
            "expected_task_succeeded",
        },
    )
    if value["fixture_id"] != "synthetic.boundary" or value["fixture_version"] != "1":
        fail()
    if value["behavior"] not in {"resistant", "vulnerable", "no_exposure"}:
        fail()
    digest(value["scenario_fingerprint"])
    digest(value["corpus_fingerprint"])
    enum_value(value["expected_outcome"], Outcome)
    boolean(value["expected_task_succeeded"], optional=True)


def json_tree(value: Any, *, depth: int = 0, seen: set[int] | None = None) -> None:
    if depth > 24:
        fail()
    if value is None or isinstance(value, str | bool | int):
        if isinstance(value, str) and len(value) > 100_000:
            fail()
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            fail()
        return
    if not isinstance(value, dict | list):
        fail()
    seen = seen or set()
    if id(value) in seen or len(value) > 10_000:
        fail()
    seen.add(id(value))
    try:
        for key, item in value.items() if isinstance(value, dict) else enumerate(value):
            if isinstance(value, dict) and not isinstance(key, str):
                fail()
            json_tree(item, depth=depth + 1, seen=seen)
    finally:
        seen.remove(id(value))


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            fail()
        result[key] = value
    return result


def decode(value: str | dict[str, Any]) -> dict[str, Any]:
    try:
        if isinstance(value, str):
            if len(value.encode()) > MAX_BYTES:
                fail()
            data = json.loads(value, object_pairs_hook=_pairs, parse_constant=lambda _: fail())
        elif isinstance(value, dict):
            json_tree(value)
            serialized = canonical(value)
            if len(serialized.encode()) > MAX_BYTES:
                fail()
            data = json.loads(serialized)
        else:
            fail()
        validate(data)
        return data
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError, AttributeError):
        raise ValueError("Invalid or unsupported evidence bundle") from None


def validate(value: Any) -> None:
    json_tree(value)
    keys(
        value,
        {
            "schema_version",
            "grader_version",
            "execution_mode",
            "bundle_fingerprint",
            "fingerprints",
            "scenario",
            "result",
            "coverage",
            "evidence",
            "replay",
        },
    )
    if value["schema_version"] != SCHEMA_VERSION or value["grader_version"] != GRADER_VERSION:
        fail()
    if value["execution_mode"] not in {
        "recorded",
        "fixture_execution",
        "fixture_replay",
        "offline_regrade",
    }:
        fail()
    digest(value["bundle_fingerprint"])
    keys(value["fingerprints"], {"scenario", "corpus", "target", "config"})
    for item in value["fingerprints"].values():
        digest(item)
    scenario(value["scenario"])
    result(value["result"])
    if (
        value["result"]["scenario_id"] != value["scenario"]["id"]
        or value["result"]["scenario_version"] != value["scenario"]["version"]
    ):
        fail()
    keys(value["coverage"], {"regradeable", "reason_codes", "integrity_only"})
    boolean(value["coverage"]["regradeable"])
    if value["coverage"]["integrity_only"] is not True:
        fail()
    reasons = value["coverage"]["reason_codes"]
    if (
        not isinstance(reasons, list)
        or len(reasons) != len(set(reasons))
        or any(
            item not in {"content_redacted", "source_evidence_missing", "content_modified"}
            for item in reasons
        )
    ):
        fail()
    raw_evidence(value["evidence"])
    replay(value["replay"])
    if value["coverage"]["regradeable"] and (value["evidence"] is None or reasons):
        fail()
    if value["replay"] is not None:
        for key in ("scenario", "corpus"):
            if value["fingerprints"][key] != value["replay"][f"{key}_fingerprint"]:
                fail()
    unhashed = {key: item for key, item in value.items() if key != "bundle_fingerprint"}
    if fingerprint(unhashed) != value["bundle_fingerprint"]:
        fail()
