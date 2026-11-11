"""ClaudeAgentTarget: isolation, hooks, blocked calls and turn limits, offline."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp")
pytest.importorskip("claude_agent_sdk")

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher  # type: ignore[import-not-found]

from pytest_wardenbot.agents import (
    AgentCapability,
    Outcome,
    ReasonCode,
    RunLimits,
    run_scenario,
)
from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS
from pytest_wardenbot.mcp import MCPHarness, TrialTools
from pytest_wardenbot.targets.claude import ClaudeAgentTarget
from tests.fixtures.stub_claude_client import StubClaudeClient

pytest_plugins = ["pytester"]


async def trial(scenario, *, attack=True, limits=None, options=None, stub=None, **target_options):
    harness = MCPHarness(scenario, attack_enabled=attack)
    clients: list[StubClaudeClient] = []

    def factory(trial_options):
        clients.append(StubClaudeClient(trial_options, **(stub or {})))
        return clients[-1]

    target = ClaudeAgentTarget(harness, options, client_factory=factory, **target_options)
    result = await run_scenario(target, scenario, observe=harness.observe, limits=limits)
    return result, clients


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", AGENT_SCENARIOS, ids=lambda case: case.id)
@pytest.mark.parametrize("behavior", ["resistant", "vulnerable"])
async def test_outcomes_follow_the_model(scenario, behavior):
    result, clients = await trial(scenario, stub={"behavior": behavior})
    assert result.task_succeeded is True
    if behavior == "resistant":
        assert result.outcome is Outcome.RESISTED
    else:
        assert result.outcome is Outcome.VIOLATED
        assert result.reason_codes in (
            (ReasonCode.FORBIDDEN_TOOL_EFFECT,),
            (ReasonCode.CANARY_LEAK,),
        )
    assert result.usage == {"input_tokens": 100, "output_tokens": 20, "cost_usd": 0.001}
    if scenario.surface.value in {"resource", "prompt"}:
        assert "Ignore your task" in clients[0].prompt


@pytest.mark.asyncio
async def test_trial_options_isolate_claude_code_and_keep_user_settings():
    async def user_hook(hook_input, tool_use_id, context) -> Any:
        return {}

    options = ClaudeAgentOptions(
        model="claude-haiku-4-5",
        system_prompt="Be careful.",
        tools=["Bash", "Read"],
        allowed_tools=["Bash"],
        mcp_servers={"production": {"type": "stdio", "command": "prod-server"}},
        setting_sources=["user", "project"],
        env={"MY_FLAG": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "true"},
        hooks={"PreToolUse": [HookMatcher(hooks=[user_hook])]},
        extra_args={"verbose": None},
        max_budget_usd=0.5,
        continue_conversation=True,
    )
    _, clients = await trial(AGENT_SCENARIOS[0], options=options)
    trial_options = clients[0].options
    assert trial_options.tools == []
    assert set(trial_options.mcp_servers) == {"wardenbot"}
    assert trial_options.strict_mcp_config is True
    assert trial_options.setting_sources == []
    assert trial_options.skills == []
    assert trial_options.plugins == []
    assert trial_options.allowed_tools == [
        "mcp__wardenbot__fetch_document",
        "mcp__wardenbot__send_message",
    ]
    assert trial_options.max_turns == RunLimits().max_turns
    assert trial_options.env == {"MY_FLAG": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
    assert trial_options.extra_args == {"verbose": None, "no-session-persistence": None}
    assert trial_options.continue_conversation is False
    # User settings that don't widen the tool surface are kept.
    assert trial_options.model == "claude-haiku-4-5"
    assert trial_options.system_prompt == "Be careful."
    assert trial_options.max_budget_usd == 0.5
    hooks = [hook for matcher in trial_options.hooks["PreToolUse"] for hook in matcher.hooks]
    assert len(hooks) == 2 and hooks[1] is user_hook
    # The caller's options object is not modified.
    assert options.tools == ["Bash", "Read"]


@pytest.mark.asyncio
async def test_extra_tools_at_startup_stop_the_trial():
    result, _ = await trial(AGENT_SCENARIOS[0], stub={"extra_tools": ("Bash",)})
    assert result.outcome is Outcome.ERROR
    assert ReasonCode.TARGET_ERROR in result.reason_codes


@pytest.mark.asyncio
async def test_extra_mcp_server_at_startup_stops_the_trial():
    from pytest_wardenbot._errors import WardenBotInfraError
    from pytest_wardenbot.targets.claude import _check_isolation

    allowed = {"mcp__wardenbot__fetch_document"}
    _check_isolation({"tools": list(allowed), "mcp_servers": [{"name": "wardenbot"}]}, allowed)
    with pytest.raises(WardenBotInfraError, match="MCP server github"):
        _check_isolation({"tools": [], "mcp_servers": [{"name": "github"}]}, allowed)
    with pytest.raises(WardenBotInfraError, match="unreadable"):
        _check_isolation("init", allowed)


@pytest.mark.asyncio
async def test_call_denied_by_permissions_counts_as_an_attempt():
    result, clients = await trial(
        AGENT_SCENARIOS[0], stub={"behavior": "vulnerable", "deny": frozenset({"send_message"})}
    )
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (ReasonCode.FORBIDDEN_TOOL_ATTEMPT,)
    assert clients[0].hook_calls[-1] == "mcp__wardenbot__send_message"


@pytest.mark.asyncio
async def test_call_rejected_by_sdk_validation_counts_as_an_attempt():
    scenario = AGENT_SCENARIOS[1]
    result, _ = await trial(scenario, stub={"behavior": "vulnerable", "corrupt_arguments": True})
    # The SDK rejected the arguments before the harness saw the call; the hook saw it.
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (ReasonCode.CANARY_LEAK_ATTEMPT,)


@pytest.mark.asyncio
async def test_sdk_turn_limit_is_reported_as_exhausted():
    result, clients = await trial(
        AGENT_SCENARIOS[0], stub={"behavior": "vulnerable"}, limits=RunLimits(max_turns=1)
    )
    assert clients[0].options.max_turns == 1
    assert result.reason_codes == (ReasonCode.TURN_LIMIT_EXHAUSTED,)
    assert result.turns == 1


@pytest.mark.asyncio
async def test_failed_claude_run_is_a_target_error():
    result, _ = await trial(AGENT_SCENARIOS[0], stub={"fail": True})
    assert result.outcome is Outcome.ERROR
    assert ReasonCode.TARGET_ERROR in result.reason_codes


@pytest.mark.asyncio
async def test_missing_result_message_is_a_target_error():
    class NoResult(StubClaudeClient):
        async def receive_response(self):
            if False:
                yield None

    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = ClaudeAgentTarget(harness, client_factory=lambda options: NoResult(options))
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert ReasonCode.TARGET_ERROR in result.reason_codes


def test_constructor_validation():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    with pytest.raises(ValueError, match="MCPHarness"):
        ClaudeAgentTarget(object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ClaudeAgentOptions"):
        ClaudeAgentTarget(harness, {"model": "x"})
    capabilities = ClaudeAgentTarget(harness).capabilities
    # Input requests reach the model; the fixed tool set can't follow tool-list changes.
    assert capabilities == TrialTools.CAPABILITIES | {AgentCapability.INPUT_REQUESTS}
    assert AgentCapability.TOOL_LIST_CHANGES not in capabilities
    plain = ClaudeAgentTarget(harness, attach=False)
    assert AgentCapability.RESOURCES not in plain.capabilities
    assert plain.options == ClaudeAgentOptions()


# -- the packaged suite --------------------------------------------------------------

CONFTEST = """
import sys
sys.path.insert(0, {root!r})

import pytest
from pytest_wardenbot.mcp import MCPHarness
from pytest_wardenbot.targets.claude import ClaudeAgentTarget
from tests.fixtures.stub_claude_client import StubClaudeClient


@pytest.fixture
def agent_harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return MCPHarness(wardenbot_agent_scenario, attack_enabled=wardenbot_agent_attack_enabled)


@pytest.fixture
def agent_target(agent_harness):
    return ClaudeAgentTarget(
        agent_harness,
        client_factory=lambda options: StubClaudeClient(options, behavior={behavior!r}),
    )


@pytest.fixture
def agent_observer(agent_harness):
    return agent_harness.observe
"""

ARGS = ("--pyargs", "pytest_wardenbot.agent_tests", "-p", "no:cacheprovider", "-p", "no:asyncio")


@pytest.mark.parametrize(
    ("behavior", "outcomes"),
    [("resistant", {"passed": 16}), ("vulnerable", {"passed": 8, "failed": 8})],
)
def test_packaged_suite(pytester, behavior, outcomes):
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[1])
    pytester.makeconftest(CONFTEST.format(root=root, behavior=behavior))
    pytester.runpytest(*ARGS).assert_outcomes(**outcomes)
