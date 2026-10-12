"""Opt-in application packs through real pytest collection and coverage gates."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pytest_wardenbot.agents.packs import APPLICATION_PACKS, ApplicationPack

pytest_plugins = ["pytester"]
ARGS = ("--pyargs", "pytest_wardenbot.agent_tests")
CONFTEST = """
import pytest
from pytest_wardenbot.agents.packs import (
    ApplicationHarness, ScriptedApplicationTarget, application_spec,
)
BEHAVIOR = "resistant"

@pytest.fixture
def application(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return ApplicationHarness(
        application_spec(wardenbot_agent_scenario.id),
        variant="attack" if wardenbot_agent_attack_enabled else "benign",
        enforce_boundaries=BEHAVIOR != "vulnerable",
    )

@pytest.fixture
def agent_target(application):
    return ScriptedApplicationTarget(application, behavior=BEHAVIOR)

@pytest.fixture
def agent_observer(application):
    return application.observe
"""


def configure(pytester, behavior="resistant", extra=""):
    pytester.makeconftest(
        CONFTEST.replace('BEHAVIOR = "resistant"', f'BEHAVIOR = "{behavior}"') + extra
    )


def test_all_application_cases_are_opt_in_and_have_real_paired_coverage(pytester):
    configure(pytester)
    path = pytester.path / "application.xml"
    result = pytester.runpytest(
        *ARGS,
        "--wardenbot-agent-pack=application",
        "--wardenbot-agent-required",
        f"--junitxml={path}",
    )
    result.assert_outcomes(passed=2 * len(APPLICATION_PACKS))
    assert result.ret == 0
    assert "Required agent coverage complete" in result.stdout.str()
    properties = [
        {
            prop.attrib["name"]: prop.attrib["value"]
            for prop in node.findall("./properties/property")
        }
        for node in ET.fromstring(path.read_text()).findall(".//testcase")
    ]
    assert {row["wardenbot.agent.pack"] for row in properties} == {
        pack.value for pack in ApplicationPack
    }
    for row in properties:
        assert row["wardenbot.agent.task_succeeded"] == "true"
        expected = "resisted" if row["wardenbot.agent.phase"] == "attack" else "inconclusive"
        assert row["wardenbot.agent.outcome"] == expected


@pytest.mark.parametrize("pack", list(ApplicationPack))
def test_select_one_pack_and_deduplicate(pytester, pack):
    configure(pytester)
    result = pytester.runpytest(
        *ARGS,
        f"--wardenbot-agent-pack={pack.value}",
        f"--wardenbot-agent-pack={pack.value}",
        "--wardenbot-agent-required",
    )
    result.assert_outcomes(passed=2 * sum(spec.pack is pack for spec in APPLICATION_PACKS))


def test_explicit_application_scenario_selects_without_pack_flag(pytester):
    configure(pytester)
    case = APPLICATION_PACKS[0].scenario
    result = pytester.runpytest(*ARGS, f"--wardenbot-agent-scenario={case.id}@{case.version}")
    result.assert_outcomes(passed=2)


def test_scenario_can_narrow_selected_pack_but_cannot_escape_it(pytester):
    configure(pytester)
    case = APPLICATION_PACKS[0].scenario
    result = pytester.runpytest(
        *ARGS,
        "--wardenbot-agent-pack=application",
        f"--wardenbot-agent-scenario={case.id}",
    )
    result.assert_outcomes(passed=2)
    rejected = pytester.runpytest(
        *ARGS,
        "--wardenbot-agent-pack=mcp",
        f"--wardenbot-agent-scenario={case.id}",
    )
    assert rejected.ret == pytest.ExitCode.USAGE_ERROR
    assert "outside the selected agent packs" in rejected.stderr.str()


def test_coverage_gate_catches_application_deselection(pytester):
    configure(pytester)
    result = pytester.runpytest(
        *ARGS,
        "--wardenbot-agent-pack=application",
        "--wardenbot-agent-required",
        "-k",
        "baseline",
    )
    result.assert_outcomes(passed=len(APPLICATION_PACKS), deselected=len(APPLICATION_PACKS))
    assert result.ret != 0
    assert "Required agent coverage incomplete" in result.stdout.str()


@pytest.mark.parametrize("behavior", ["vulnerable", "no_exposure"])
def test_application_bad_controls_cannot_pass_required_gate(pytester, behavior):
    configure(pytester, behavior)
    result = pytester.runpytest(
        *ARGS,
        "--wardenbot-agent-pack=application",
        "--wardenbot-agent-required",
    )
    result.assert_outcomes(passed=len(APPLICATION_PACKS), failed=len(APPLICATION_PACKS))
    assert result.ret != 0
    if behavior == "vulnerable":
        assert "Confirmed boundary violation" in result.stdout.str()
    else:
        assert "outcome=inconclusive" in result.stdout.str()


def test_new_pack_warning_text_is_not_published(pytester):
    configure(
        pytester,
        extra="""
import warnings
@pytest.fixture(autouse=True)
def warn_about_private_data():
    warnings.warn("SYNTHETIC_PRIVATE_PACK_WARNING")
""",
    )
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-pack=application")
    result.assert_outcomes(passed=2 * len(APPLICATION_PACKS))
    assert "SYNTHETIC_PRIVATE_PACK_WARNING" not in result.stdout.str()
    assert "Agent trial warning details omitted" in result.stdout.str()
