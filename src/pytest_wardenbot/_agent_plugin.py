"""Agent pytest integration, isolated from the established chatbot suite."""

from __future__ import annotations

import asyncio
import warnings
from dataclasses import dataclass, field
from typing import Any, cast

import pytest

from pytest_wardenbot.agents.contracts import (
    AgentTarget,
    Outcome,
    ReasonCode,
    RunLimits,
    RunResult,
    Scenario,
)
from pytest_wardenbot.agents.evaluation import required_capabilities
from pytest_wardenbot.agents.evidence import EVIDENCE_GRADER_VERSION
from pytest_wardenbot.agents.runner import Observer, run_scenario
from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS, scenario_selection_id

CaseKey = tuple[str, str, str]


@dataclass
class _Coverage:
    expected: set[CaseKey] = field(default_factory=set)
    completed: set[CaseKey] = field(default_factory=set)


_COVERAGE: pytest.StashKey[_Coverage] = pytest.StashKey()


class _CoverageReporter:
    """One ledger path for local reports and serialized xdist worker reports."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        properties = dict(report.user_properties)
        key = (
            properties.get("wardenbot.agent.scenario_id"),
            properties.get("wardenbot.agent.version"),
            properties.get("wardenbot.agent.phase"),
        )
        if not all(isinstance(value, str) for value in key):
            return
        key = cast(CaseKey, key)
        coverage = self.config.stash[_COVERAGE]
        if key not in coverage.expected:
            return
        if (
            report.when == "call"
            and report.passed
            and not hasattr(report, "wasxfail")
            and properties.get("wardenbot.agent.coverage_complete") == "true"
        ):
            coverage.completed.add(key)
        if report.when == "teardown" and (report.failed or report.skipped):
            coverage.completed.discard(key)


def add_options(group: pytest.OptionGroup) -> None:
    group.addoption(
        "--wardenbot-agent-scenario",
        action="append",
        default=[],
        metavar="ID[@VERSION]",
        help="Select a bundled agent scenario (repeatable); default: all eight scenarios.",
    )
    group.addoption(
        "--wardenbot-agent-required",
        action="store_true",
        default=False,
        help="Require complete baseline and attack coverage for every selected agent scenario.",
    )


def _selected(config: pytest.Config) -> tuple[Scenario, ...]:
    selectors = config.getoption("wardenbot_agent_scenario", default=[])
    if not selectors:
        return AGENT_SCENARIOS
    lookup = {
        key: scenario
        for scenario in AGENT_SCENARIOS
        for key in (scenario.id, scenario_selection_id(scenario))
    }
    if any(selector not in lookup for selector in selectors):
        available = ", ".join(scenario_selection_id(case) for case in AGENT_SCENARIOS)
        raise pytest.UsageError(
            "Unknown --wardenbot-agent-scenario. Available versioned IDs: " + available
        )
    requested = {lookup[selector].id for selector in selectors}
    return tuple(case for case in AGENT_SCENARIOS if case.id in requested)


def configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "wardenbot_agent(surface, assertion, scenario_id, version, phase): "
        "instrumented agent scenario; phase is baseline or attack",
    )
    config.addinivalue_line(
        "markers", "wardenbot_agent_capability(name): required agent integration capability"
    )
    config.stash[_COVERAGE] = _Coverage(
        expected={
            (case.id, case.version, phase)
            for case in _selected(config)
            for phase in ("baseline", "attack")
        }
    )
    config.pluginmanager.register(_CoverageReporter(config), "wardenbot-agent-coverage-reporter")


def generate_tests(metafunc: pytest.Metafunc) -> None:
    if metafunc.function.__name__ != "test_agent_security":
        return
    names = ("wardenbot_agent_scenario", "wardenbot_agent_attack_enabled")
    if not set(names) <= set(metafunc.fixturenames):
        return
    parameters = []
    for case in _selected(metafunc.config):
        assertion = "forbidden-tool" if case.forbidden_tool is not None else "canary"
        for attack_enabled in (False, True):
            phase = "attack" if attack_enabled else "baseline"
            markers = [
                pytest.mark.wardenbot_agent(
                    surface=case.surface.value,
                    assertion=assertion,
                    scenario_id=case.id,
                    version=case.version,
                    phase=phase,
                ),
                *[
                    pytest.mark.wardenbot_agent_capability(capability.value)
                    for capability in sorted(required_capabilities(case))
                ],
            ]
            parameters.append(
                pytest.param(
                    case,
                    attack_enabled,
                    id=f"{scenario_selection_id(case)}-{phase}",
                    marks=markers,
                )
            )
    metafunc.parametrize(names, parameters, indirect=True)


def _case_key(item: pytest.Item) -> CaseKey | None:
    for marker in item.iter_markers("wardenbot_agent"):
        if {"scenario_id", "version", "phase"} <= marker.kwargs.keys():
            return (
                marker.kwargs["scenario_id"],
                marker.kwargs["version"],
                marker.kwargs["phase"],
            )
    return None


def record_report(item: pytest.Item, report: pytest.TestReport) -> None:
    key = _case_key(item)
    if key is None:
        return
    if (report.failed or report.skipped) and not any(
        name == "wardenbot.agent.outcome" for name, _ in report.user_properties
    ):
        properties = [
            ("wardenbot.agent.scenario_id", key[0]),
            ("wardenbot.agent.version", key[1]),
            ("wardenbot.agent.phase", key[2]),
            ("wardenbot.agent.outcome", "inconclusive" if report.skipped else "error"),
            (
                "wardenbot.agent.reason_codes",
                "pytest_skip" if report.skipped else "pytest_error",
            ),
        ]
        report.user_properties.extend(properties)
        item.user_properties.extend(properties)
    # User fixture construction/teardown and captured target output can include
    # secrets before a RunResult exists. The packaged suite publishes structural
    # diagnostics only; never embed those exception chains or capture sections.
    report.sections.clear()
    if hasattr(report, "wasxfail"):
        # JUnit and terminal reporting use this field directly rather than the
        # sanitized longrepr. A caller's xfail reason can contain free text.
        report.wasxfail = "Agent case marked xfail"
    properties = dict(report.user_properties)
    diagnostic = (
        f"Agent {key[2]}: outcome={properties.get('wardenbot.agent.outcome', 'error')}; "
        f"task_succeeded={properties.get('wardenbot.agent.task_succeeded', 'unknown')}; "
        f"reasons={properties.get('wardenbot.agent.reason_codes', 'pytest_error')}"
    )
    reason_codes = properties.get("wardenbot.agent.reason_codes", "")
    if isinstance(reason_codes, str) and "missing_agent_target" in reason_codes:
        diagnostic += (
            ". No `agent_target` fixture configured. Override it with your AgentTarget; "
            "see docs/how-to/agent-scenarios.md"
        )
    elif isinstance(reason_codes, str) and "no_harness_trace" in reason_codes:
        diagnostic += ". Override `agent_observer` with an independent harness.observe callback"
    if report.failed:
        label = (
            "Confirmed boundary violation"
            if properties.get("wardenbot.agent.outcome") == "violated"
            else "Agent case failed"
        )
        report.longrepr = label + ". " + diagnostic
    elif report.skipped:
        report.longrepr = (
            str(item.path),
            item.location[1] or 0,
            "Agent case skipped. " + diagnostic,
        )


def session_finish(session: pytest.Session) -> None:
    if hasattr(session.config, "workerinput"):
        return  # Each xdist worker owns only a subset; the controller audits all reports.
    if session.config.getoption("wardenbot_agent_required", default=False):
        coverage = session.config.stash[_COVERAGE]
        if coverage.expected - coverage.completed and session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def terminal_summary(terminalreporter: Any) -> None:
    config = terminalreporter.config
    if not config.getoption("wardenbot_agent_required", default=False):
        return
    coverage = config.stash[_COVERAGE]
    missing = sorted(coverage.expected - coverage.completed)
    if missing:
        terminalreporter.write_sep("=", "Required agent coverage incomplete", red=True)
        for scenario_id, version, phase in missing:
            terminalreporter.write_line(f"  {scenario_id}@{version}-{phase}")
    else:
        terminalreporter.write_line("Required agent coverage complete", green=True)


def sanitize_warning(warning_message: warnings.WarningMessage, nodeid: str) -> None:
    """Pytest's warning summary is separate from captured report sections."""
    if "::test_agent_security[" not in nodeid:
        return
    if not any(
        nodeid.endswith(f"[{scenario_selection_id(case)}-{phase}]")
        for case in AGENT_SCENARIOS
        for phase in ("baseline", "attack")
    ):
        return
    warning_message.message = Warning("Agent trial warning details omitted from reports")
    warning_message.line = "Agent trial warning details omitted from reports"
    warning_message.source = None


@pytest.fixture
def wardenbot_agent_scenario(request: pytest.FixtureRequest) -> Scenario:
    return request.param


@pytest.fixture
def wardenbot_agent_attack_enabled(request: pytest.FixtureRequest) -> bool:
    """Target/harness factories use this flag for paired benign/attack trials."""
    return bool(request.param)


@pytest.fixture
def agent_target(request: pytest.FixtureRequest) -> AgentTarget:
    key = _case_key(request.node)
    if key is not None:
        request.node.user_properties.extend(
            [
                ("wardenbot.agent.scenario_id", key[0]),
                ("wardenbot.agent.version", key[1]),
                ("wardenbot.agent.phase", key[2]),
                ("wardenbot.agent.outcome", "error"),
                ("wardenbot.agent.reason_codes", "missing_agent_target"),
            ]
        )
    pytest.fail(
        "No `agent_target` fixture configured. Override it with your AgentTarget; "
        "build its controlled input using `wardenbot_agent_scenario` and "
        "`wardenbot_agent_attack_enabled`. See docs/how-to/agent-scenarios.md.",
        pytrace=False,
    )


@pytest.fixture
def agent_observer() -> Observer | None:
    """Override with an independent authoritative harness.observe callback."""
    return None


@pytest.fixture
def wardenbot_agent_limits() -> RunLimits:
    return RunLimits()


@pytest.fixture
def wardenbot_agent_result(
    request: pytest.FixtureRequest,
    agent_target: AgentTarget,
    agent_observer: Observer | None,
    wardenbot_agent_scenario: Scenario,
    wardenbot_agent_attack_enabled: bool,
    wardenbot_agent_limits: RunLimits,
) -> RunResult:
    result = asyncio.run(
        run_scenario(
            agent_target,
            wardenbot_agent_scenario,
            observe=agent_observer,
            limits=wardenbot_agent_limits,
        )
    )
    phase = "attack" if wardenbot_agent_attack_enabled else "baseline"
    request.node.user_properties.extend(
        [
            ("wardenbot.agent.scenario_id", result.scenario_id),
            ("wardenbot.agent.version", result.scenario_version),
            ("wardenbot.agent.phase", phase),
            ("wardenbot.agent.outcome", result.outcome.value),
            ("wardenbot.agent.exposure", result.exposure.value),
            ("wardenbot.agent.task_succeeded", str(result.task_succeeded).lower()),
            ("wardenbot.agent.grader_version", EVIDENCE_GRADER_VERSION),
            ("wardenbot.agent.evidence_scope", "declared_local_boundary"),
            (
                "wardenbot.agent.reason_codes",
                ",".join(reason.value for reason in result.reason_codes),
            ),
        ]
    )
    return result


def assert_case(
    item: pytest.Item, result: RunResult, *, attack_enabled: bool, required: bool
) -> None:
    """Keep domain outcomes explicit without embedding evidence payloads."""
    phase = "attack" if attack_enabled else "baseline"
    reasons = ",".join(reason.value for reason in result.reason_codes) or "none"
    diagnostic = (
        f"Agent {phase}: outcome={result.outcome.value}; "
        f"exposure={result.exposure.value}; "
        f"task_succeeded={str(result.task_succeeded).lower()}; reasons={reasons}"
    )
    if result.outcome is Outcome.UNSUPPORTED and not required:
        pytest.skip(diagnostic)
    if attack_enabled:
        if result.outcome is not Outcome.RESISTED:
            label = (
                "Confirmed boundary violation"
                if result.outcome is Outcome.VIOLATED
                else "Incomplete agent security evidence"
            )
            pytest.fail(label + ". " + diagnostic, pytrace=False)
    elif result.outcome is not Outcome.INCONCLUSIVE or result.reason_codes != (
        ReasonCode.MISSING_EXPOSURE,
    ):
        pytest.fail(
            "Benign baseline lacks valid independent evidence. " + diagnostic, pytrace=False
        )
    if result.task_succeeded is not True:
        pytest.fail("Legitimate task did not succeed. " + diagnostic, pytrace=False)
    item.user_properties.append(("wardenbot.agent.coverage_complete", "true"))
