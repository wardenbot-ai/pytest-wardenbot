"""The OpenAI Agents SDK recipe runs the packaged agent suite offline."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("agents")

pytest_plugins = ["pytester"]

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "openai_agents" / "conftest.py"
ARGS = ("--pyargs", "pytest_wardenbot.agent_tests", "-p", "no:cacheprovider", "-p", "no:asyncio")

OFFLINE = """

import sys
sys.path.insert(0, {root!r})
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from tests.fixtures.scripted_chat_model import ScriptedChatModel

SCRIPTED = ScriptedChatModel({behavior!r})


@pytest.fixture
def agent_target(agent_harness):
    client = AsyncOpenAI(
        api_key="offline",  # pragma: allowlist secret
        base_url="http://offline.invalid/v1",
        http_client=SCRIPTED.http_client(),
        max_retries=0,
    )
    return OpenAIAgentsTarget(
        agent_harness, OpenAIChatCompletionsModel(model="scripted", openai_client=client)
    )
"""


def configure(pytester, behavior):
    pytester.makeconftest(EXAMPLE.read_text() + OFFLINE.format(root=str(ROOT), behavior=behavior))


def test_recipe_resists_on_all_eight_scenarios(pytester):
    configure(pytester, "resistant")
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-required")
    result.assert_outcomes(passed=16)


def test_recipe_catches_a_vulnerable_model(pytester):
    configure(pytester, "vulnerable")
    result = pytester.runpytest(*ARGS)
    result.assert_outcomes(passed=8, failed=8)


def test_turn_limit_stops_before_the_next_model_request(pytester):
    pytester.makeconftest(
        EXAMPLE.read_text()
        + OFFLINE.format(root=str(ROOT), behavior="vulnerable")
        + "\n\nfrom pytest_wardenbot.agents import RunLimits\n\n"
        + "@pytest.fixture\ndef wardenbot_agent_limits():\n    return RunLimits(max_turns=4)\n"
    )
    result = pytester.runpytest(
        *ARGS, "--wardenbot-agent-scenario=mcp.tool-result.forbidden-tool@2"
    )
    # Baseline: discovery, model, fetch, final answer fit in four turns.
    # Attack: no turn was left for the sink call, so it was blocked and counted.
    result.assert_outcomes(passed=1, failed=1)
    assert "reasons=forbidden_tool_attempt,turn_limit_exhausted" in result.stdout.str()
