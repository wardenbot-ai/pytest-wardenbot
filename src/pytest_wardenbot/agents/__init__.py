"""Additive agent contracts, separate from the legacy chatbot adapter path."""

from pytest_wardenbot.agents._privacy import PrivacyPolicy
from pytest_wardenbot.agents.contracts import (
    AgentCapability,
    AgentEvent,
    AgentTarget,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    Exposure,
    HarnessTrace,
    Outcome,
    ReasonCode,
    RunLimits,
    RunResult,
    Scenario,
    TargetRun,
)
from pytest_wardenbot.agents.evaluation import evaluate, required_capabilities
from pytest_wardenbot.agents.reporting import (
    format_result,
    render_result_html,
    result_to_dict,
    result_to_json,
    to_legacy_attack_result,
)
from pytest_wardenbot.agents.runner import run_scenario

__all__ = [
    "AgentCapability",
    "AgentEvent",
    "AgentTarget",
    "AttackSurface",
    "EventKind",
    "EventProvenance",
    "EventTrust",
    "Exposure",
    "HarnessTrace",
    "Outcome",
    "PrivacyPolicy",
    "ReasonCode",
    "RunLimits",
    "RunResult",
    "Scenario",
    "TargetRun",
    "evaluate",
    "format_result",
    "render_result_html",
    "required_capabilities",
    "result_to_dict",
    "result_to_json",
    "run_scenario",
    "to_legacy_attack_result",
]
