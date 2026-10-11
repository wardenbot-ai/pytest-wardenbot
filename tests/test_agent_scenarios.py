"""Consumer-facing collection, outcomes, privacy and required-coverage gates."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS, scenario_selection_id

pytest_plugins = ["pytester"]

SELECTION = "mcp.tool-result.forbidden-tool@1"
ARGS = ("--pyargs", "pytest_wardenbot.agent_tests")

CONFTEST = """
import pytest
from pytest_wardenbot.agents import (
    AgentCapability, AgentEvent, EventKind, EventProvenance, EventTrust,
    HarnessTrace, TargetRun,
)

BEHAVIOR = "resistant"
PRIVATE = "SYNTHETIC_PRIVATE_TARGET_ARGUMENT"

class Harness:
    def __init__(self, case, attack_enabled):
        self.case = case
        self.attack_enabled = attack_enabled
        self.traces = {}
    def observe(self, trial_id):
        return self.traces[trial_id]

class Target:
    name = "scripted-offline"
    capabilities = frozenset(AgentCapability)
    def __init__(self, harness):
        self.harness = harness
    async def reset(self, trial_id):
        pass
    async def run(self, task, *, trial_id, max_turns):
        harness = self.harness
        case = harness.case
        events = []
        if harness.attack_enabled and BEHAVIOR != "no_exposure":
            events.append(AgentEvent(
                trial_id, EventKind(case.surface.value),
                EventProvenance.HARNESS, EventTrust.OBSERVED,
                scenario_id=case.id, scenario_version=case.version,
                surface=case.surface, data={"arguments": PRIVATE},
            ))
        if harness.attack_enabled and BEHAVIOR == "vulnerable":
            events.append(AgentEvent(
                trial_id, EventKind.TOOL_EFFECT,
                EventProvenance.HARNESS, EventTrust.OBSERVED,
                name=case.forbidden_tool or "allowed_sink",
                data={"value": case.canary or PRIVATE},
            ))
        harness.traces[trial_id] = HarnessTrace(trial_id, tuple(events), complete=True)
        if BEHAVIOR == "error":
            print(PRIVATE)
            raise RuntimeError(PRIVATE)
        return TargetRun(task_succeeded=BEHAVIOR != "refuse_everything",
                         turns=1, final_text=PRIVATE)

@pytest.fixture
def agent_harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return Harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled)

@pytest.fixture
def agent_target(agent_harness):
    target = Target(agent_harness)
    if BEHAVIOR == "unsupported":
        target.capabilities = frozenset()
    return target

@pytest.fixture
def agent_observer(agent_harness):
    return agent_harness.observe
"""


def configure(pytester: pytest.Pytester, behavior="resistant", extra=""):
    pytester.makeconftest(
        CONFTEST.replace('BEHAVIOR = "resistant"', f'BEHAVIOR = "{behavior}"') + extra
    )


def run_one(pytester: pytest.Pytester, *extra: str):
    return pytester.runpytest(*ARGS, f"--wardenbot-agent-scenario={SELECTION}", *extra)


def test_corpus_is_small_unique_versioned_and_contains_separate_assertions():
    assert len(AGENT_SCENARIOS) == 8
    assert len({scenario_selection_id(case) for case in AGENT_SCENARIOS}) == 8
    assert all((case.canary is None) != (case.forbidden_tool is None) for case in AGENT_SCENARIOS)
    assert len({case.surface for case in AGENT_SCENARIOS}) == 4


def test_installed_pyargs_pairs_all_baselines_and_attack_cases(pytester):
    configure(pytester)
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-required", "--strict-markers")
    result.assert_outcomes(passed=16)
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*Required agent coverage complete*"])


@pytest.mark.parametrize(
    "behavior,passed,failed",
    [("vulnerable", 8, 8), ("no_exposure", 8, 8), ("refuse_everything", 0, 16)],
)
def test_every_bundled_case_has_vulnerable_no_exposure_and_utility_controls(
    pytester, behavior, passed, failed
):
    configure(pytester, behavior)
    result = pytester.runpytest(*ARGS)
    result.assert_outcomes(passed=passed, failed=failed)


@pytest.mark.parametrize(
    "behavior,passed,failed",
    [("resistant", 16, 0), ("vulnerable", 8, 8), ("no_exposure", 8, 8)],
)
def test_real_mcp_controls_validate_each_bundled_assertion(pytester, behavior, passed, failed):
    pytest.importorskip("mcp")
    pytester.makeconftest(
        f"""
        import pytest
        from pytest_wardenbot.mcp import MCPHarness, ScriptedMCPAgentTarget
        @pytest.fixture
        def agent_harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
            return MCPHarness(wardenbot_agent_scenario,
                              attack_enabled=wardenbot_agent_attack_enabled)
        @pytest.fixture
        def agent_target(agent_harness):
            return ScriptedMCPAgentTarget(agent_harness, behavior="{behavior}")
        @pytest.fixture
        def agent_observer(agent_harness):
            return agent_harness.observe
        """
    )
    # A fresh consumer process avoids pytester's in-process sys.modules
    # restoration splitting the SDK's related class definitions.
    result = pytester.runpytest_subprocess(*ARGS)
    result.assert_outcomes(passed=passed, failed=failed)


def test_repeated_real_http_trials_own_and_close_clients_on_each_test_loop(pytester):
    pytest.importorskip("mcp")
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.mcp import MCPHarness, ScriptedMCPAgentTarget
        @pytest.fixture
        def agent_harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
            harness = MCPHarness(wardenbot_agent_scenario, transport="http",
                                 attack_enabled=wardenbot_agent_attack_enabled)
            yield harness
            assert all(resources.closed for resources in harness.resources.values())
        @pytest.fixture
        def agent_target(agent_harness):
            return ScriptedMCPAgentTarget(agent_harness)
        @pytest.fixture
        def agent_observer(agent_harness):
            return agent_harness.observe
        """
    )
    result = pytester.runpytest_subprocess(
        *ARGS,
        f"--wardenbot-agent-scenario={SELECTION}",
        "--wardenbot-agent-scenario=mcp.resource.canary@1",
        "--wardenbot-agent-required",
    )
    result.assert_outcomes(passed=4)
    assert result.ret == 0


def test_cli_selects_only_one_versioned_case_and_both_phases(pytester):
    configure(pytester)
    result = run_one(pytester, "--wardenbot-agent-required", "-v")
    result.assert_outcomes(passed=2)
    assert result.ret == 0
    assert "mcp.tool-description" not in result.stdout.str()
    result.stdout.fnmatch_lines([f"*{SELECTION}-baseline*PASSED*", f"*{SELECTION}-attack*PASSED*"])


def test_plain_id_and_duplicate_selection_are_supported(pytester):
    configure(pytester)
    result = run_one(pytester, "--wardenbot-agent-scenario=mcp.tool-result.forbidden-tool")
    result.assert_outcomes(passed=2)


def test_unknown_id_has_actionable_error_instead_of_empty_green_collection(pytester):
    configure(pytester)
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-scenario=unknown")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "Available versioned IDs" in result.stderr.str()


@pytest.mark.parametrize(
    "behavior,failed,skipped,outcome",
    [
        ("vulnerable", 1, 0, "violated"),
        ("no_exposure", 1, 0, "inconclusive"),
        ("error", 2, 0, "error"),
        ("unsupported", 0, 2, "unsupported"),
        ("refuse_everything", 2, 0, "resisted"),
    ],
)
def test_domain_outcomes_and_task_utility_remain_distinct(
    pytester, behavior, failed, skipped, outcome
):
    configure(pytester, behavior)
    result = run_one(pytester, "-rA")
    result.assert_outcomes(failed=failed, skipped=skipped, passed=2 - failed - skipped)
    assert f"outcome={outcome}" in result.stdout.str()
    assert "SYNTHETIC_PRIVATE_TARGET_ARGUMENT" not in result.stdout.str()
    if behavior != "vulnerable":
        assert "Confirmed boundary violation" not in result.stdout.str()


def test_missing_target_fixture_is_actionable_error(pytester):
    result = run_one(pytester)
    result.assert_outcomes(errors=2)
    assert result.ret != 0
    assert "outcome=error" in result.stdout.str()
    assert "No `agent_target` fixture configured" in result.stdout.str()


def test_missing_observer_cannot_establish_baseline_or_attack_coverage(pytester):
    configure(pytester, extra="\n@pytest.fixture\ndef agent_observer(): return None\n")
    result = run_one(pytester, "--wardenbot-agent-required")
    result.assert_outcomes(failed=2)
    assert "no_harness_trace" in result.stdout.str()
    assert result.ret != 0


@pytest.mark.parametrize(
    "filter_args", [("-k", "attack"), ("-k", "nothing-matches"), ("-m", "not wardenbot_agent")]
)
def test_required_mode_rejects_partial_or_zero_selected_coverage(pytester, filter_args):
    configure(pytester)
    result = run_one(pytester, "--wardenbot-agent-required", *filter_args)
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()
    assert f"{SELECTION}-baseline" in result.stdout.str()


def test_required_mode_rejects_zero_collected_agent_cases(pytester):
    pytester.makepyfile("def test_local(): assert True")
    result = pytester.runpytest("--wardenbot-agent-required")
    result.assert_outcomes(passed=1)
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()


def test_required_mode_unsupported_is_failure_and_optional_mode_is_skip(pytester):
    configure(pytester, "unsupported")
    result = run_one(pytester, "--wardenbot-agent-required")
    result.assert_outcomes(failed=2)
    assert result.ret != 0
    assert "outcome=unsupported" in result.stdout.str()


@pytest.mark.parametrize(
    "marker", ["skip(reason='private skip reason')", "xfail(reason='expected failure')"]
)
def test_required_mode_rejects_skips_and_expected_failures(pytester, marker):
    configure(pytester, "vulnerable")
    pytester.makepyfile(
        f"""
        from functools import wraps
        import pytest
        from pytest_wardenbot.agent_tests.test_security import test_agent_security as original
        @pytest.mark.{marker}
        @wraps(original)
        def test_agent_security(*args, **kwargs):
            return original(*args, **kwargs)
        """
    )
    result = pytester.runpytest(
        f"--wardenbot-agent-scenario={SELECTION}", "--wardenbot-agent-required"
    )
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()


def test_required_mode_does_not_count_unexpected_pass_as_coverage(pytester):
    configure(pytester)
    pytester.makepyfile(
        """
        from functools import wraps
        import pytest
        from pytest_wardenbot.agent_tests.test_security import test_agent_security as original
        @pytest.mark.xfail(reason="expected failure", strict=False)
        @wraps(original)
        def test_agent_security(*args, **kwargs):
            return original(*args, **kwargs)
        """
    )
    result = pytester.runpytest(
        f"--wardenbot-agent-scenario={SELECTION}", "--wardenbot-agent-required"
    )
    result.assert_outcomes(xpassed=2)
    assert result.ret != 0


def test_xfail_reason_is_sanitized_in_console_and_junit(pytester):
    configure(pytester, "vulnerable")
    pytester.makepyfile(
        """
        from functools import wraps
        import pytest
        from pytest_wardenbot.agent_tests.test_security import test_agent_security as original
        @pytest.mark.xfail(reason="SYNTHETIC_XFAIL_SECRET", strict=False)
        @wraps(original)
        def test_agent_security(*args, **kwargs):
            return original(*args, **kwargs)
        """
    )
    path = pytester.path / "xfail.xml"
    result = pytester.runpytest(
        f"--wardenbot-agent-scenario={SELECTION}", f"--junitxml={path}", "-rA"
    )
    result.assert_outcomes(xpassed=1, xfailed=1)
    assert "SYNTHETIC_XFAIL_SECRET" not in result.stdout.str()
    assert "SYNTHETIC_XFAIL_SECRET" not in path.read_text()


def test_imported_suite_collects_in_consumer_and_required_coverage_passes(pytester):
    configure(pytester)
    pytester.makepyfile(
        "from pytest_wardenbot.agent_tests.test_security import test_agent_security"
    )
    result = pytester.runpytest(
        f"--wardenbot-agent-scenario={SELECTION}", "--wardenbot-agent-required"
    )
    result.assert_outcomes(passed=2)
    assert result.ret == 0


def test_junit_preserves_domain_and_baseline_utility_without_payloads(pytester):
    configure(pytester, "vulnerable")
    path = pytester.path / "agent.xml"
    result = run_one(pytester, f"--junitxml={path}", "-o", "junit_logging=all")
    result.assert_outcomes(passed=1, failed=1)
    xml = path.read_text()
    assert "SYNTHETIC_PRIVATE_TARGET_ARGUMENT" not in xml
    nodes = ET.fromstring(xml).findall(".//testcase")
    properties = [
        {
            entry.attrib["name"]: entry.attrib["value"]
            for entry in case.findall("./properties/property")
        }
        for case in nodes
    ]
    assert properties[0]["wardenbot.agent.phase"] == "baseline"
    assert properties[0]["wardenbot.agent.outcome"] == "inconclusive"
    assert properties[0]["wardenbot.agent.coverage_complete"] == "true"
    assert properties[1]["wardenbot.agent.phase"] == "attack"
    assert properties[1]["wardenbot.agent.outcome"] == "violated"


def test_user_fixture_exception_and_capture_are_sanitized_even_before_result(pytester):
    configure(
        pytester,
        extra="""
@pytest.fixture
def agent_target():
    print('SYNTHETIC_FIXTURE_SECRET')
    raise RuntimeError('SYNTHETIC_FIXTURE_SECRET')
""",
    )
    path = pytester.path / "fixture.xml"
    result = run_one(pytester, f"--junitxml={path}", "-o", "junit_logging=all", "--showlocals")
    result.assert_outcomes(errors=2)
    assert "SYNTHETIC_FIXTURE_SECRET" not in result.stdout.str()
    assert "SYNTHETIC_FIXTURE_SECRET" not in path.read_text()


def test_malformed_overridden_result_never_exports_its_payload_or_repr(pytester):
    configure(
        pytester,
        extra="""
@pytest.fixture
def wardenbot_agent_result():
    return {'outcome': 'SYNTHETIC_MALFORMED_SECRET'}
""",
    )
    path = pytester.path / "malformed.xml"
    result = run_one(pytester, f"--junitxml={path}", "--showlocals")
    result.assert_outcomes(failed=2)
    assert "SYNTHETIC_MALFORMED_SECRET" not in result.stdout.str()
    assert "SYNTHETIC_MALFORMED_SECRET" not in path.read_text()


def test_required_coverage_rejects_user_fixture_teardown_failure(pytester):
    configure(
        pytester,
        extra="""
@pytest.fixture
def agent_target(agent_harness):
    yield Target(agent_harness)
    raise RuntimeError('SYNTHETIC_TEARDOWN_SECRET')
""",
    )
    result = run_one(pytester, "--wardenbot-agent-required", "--showlocals")
    result.assert_outcomes(passed=2, errors=2)
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()
    assert "SYNTHETIC_TEARDOWN_SECRET" not in result.stdout.str()


def test_target_warning_summary_does_not_embed_warning_message_or_source_line(pytester):
    configure(
        pytester,
        extra="""
@pytest.fixture
def agent_target(agent_harness):
    import warnings
    warnings.warn('SYNTHETIC_WARNING_SECRET', UserWarning)
    return Target(agent_harness)
""",
    )
    result = run_one(pytester)
    result.assert_outcomes(passed=2)
    assert "SYNTHETIC_WARNING_SECRET" not in result.stdout.str()
    assert "Agent trial warning details omitted" in result.stdout.str()


@pytest.mark.parametrize(
    "behavior,extra,success",
    [
        ("resistant", (), True),
        ("resistant", ("-k", "attack"), False),
        ("resistant", ("-m", "not wardenbot_agent"), False),
        ("unsupported", (), False),
        ("skipped", (), False),
        ("xpassed", (), False),
    ],
)
def test_xdist_controller_checks_complete_serialized_coverage(pytester, behavior, extra, success):
    pytest.importorskip("xdist")
    if behavior in {"skipped", "xpassed"}:
        marker = (
            "skip(reason=PRIVATE)"
            if behavior == "skipped"
            else "xfail(reason=PRIVATE, strict=False)"
        )
        configure(
            pytester,
            extra=f"""
def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.{marker})
""",
        )
    else:
        configure(pytester, behavior)
    result = pytester.runpytest_subprocess(
        *ARGS,
        f"--wardenbot-agent-scenario={SELECTION}",
        "--wardenbot-agent-required",
        "-n",
        "2",
        *extra,
    )
    assert (result.ret == 0) is success
    expected = (
        "Required agent coverage complete" if success else "Required agent coverage incomplete"
    )
    assert expected in result.stdout.str()


def test_xdist_controller_invalidates_teardown_coverage(pytester):
    pytest.importorskip("xdist")
    configure(
        pytester,
        extra="""
@pytest.fixture
def agent_target(agent_harness):
    yield Target(agent_harness)
    raise RuntimeError('SYNTHETIC_XDIST_TEARDOWN_SECRET')
""",
    )
    result = pytester.runpytest_subprocess(
        *ARGS,
        f"--wardenbot-agent-scenario={SELECTION}",
        "--wardenbot-agent-required",
        "-n",
        "2",
    )
    result.assert_outcomes(passed=2, errors=2)
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()
    assert "SYNTHETIC_XDIST_TEARDOWN_SECRET" not in result.stdout.str()
