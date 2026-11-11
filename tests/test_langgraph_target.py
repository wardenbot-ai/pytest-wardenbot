"""LangGraphAgentTarget: graph runs, turn limits, blocked calls and the tool-calling check."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("mcp")
pytest.importorskip("langgraph")
pytest.importorskip("langchain_core")

from langgraph.checkpoint.memory import InMemorySaver  # type: ignore[import-not-found]
from langgraph.graph import END, START, MessagesState, StateGraph  # type: ignore[import-not-found]
from langgraph.prebuilt import ToolNode, tools_condition  # type: ignore[import-not-found]

from pytest_wardenbot.agents import (
    AgentCapability,
    Outcome,
    ReasonCode,
    RunLimits,
    run_scenario,
)
from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS
from pytest_wardenbot.mcp import MCPHarness, TrialTools
from pytest_wardenbot.targets import langgraph as target_module
from pytest_wardenbot.targets.langgraph import LangGraphAgentTarget, message_text
from tests.fixtures.scripted_langchain_model import ScriptedToolModel

pytest_plugins = ["pytester"]


def react_graph(model: Any, tools: list, checkpointer: Any = None) -> Any:
    """A minimal tool-calling graph, without the `langchain` package."""
    bound = model.bind_tools(tools)

    async def agent(state: MessagesState) -> dict:
        return {"messages": [await bound.ainvoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)


@pytest.fixture(autouse=True)
def fresh_probe_cache():
    target_module._TOOL_CALLING.clear()
    yield
    target_module._TOOL_CALLING.clear()


async def trial(scenario, model, *, attack=True, limits=None, **options):
    harness = MCPHarness(scenario, attack_enabled=attack)
    options.setdefault("tool_calling", True)
    target = LangGraphAgentTarget(harness, lambda tools: react_graph(model, tools), **options)
    result = await run_scenario(target, scenario, observe=harness.observe, limits=limits)
    return result, target


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", AGENT_SCENARIOS, ids=lambda case: case.id)
@pytest.mark.parametrize("behavior", ["resistant", "vulnerable"])
async def test_graph_outcomes_follow_the_model(scenario, behavior):
    result, _ = await trial(scenario, ScriptedToolModel(behavior=behavior))
    assert result.task_succeeded is True
    if behavior == "resistant":
        assert result.outcome is Outcome.RESISTED
    else:
        assert result.outcome is Outcome.VIOLATED
        assert result.reason_codes in (
            (ReasonCode.FORBIDDEN_TOOL_EFFECT,),
            (ReasonCode.CANARY_LEAK,),
        )
    assert result.usage and result.usage["input_tokens"] >= 20


@pytest.mark.asyncio
async def test_model_requests_claim_turns_before_they_are_sent():
    model = ScriptedToolModel(behavior="vulnerable")
    result, _ = await trial(AGENT_SCENARIOS[0], model, limits=RunLimits(max_turns=4))
    # discovery, model, fetch, model: the sink call had no turn left.
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (
        ReasonCode.FORBIDDEN_TOOL_ATTEMPT,
        ReasonCode.TURN_LIMIT_EXHAUSTED,
    )
    assert result.turns == 4
    assert model.calls == 2


@pytest.mark.asyncio
async def test_no_turn_for_the_next_model_request_is_exhaustion():
    model = ScriptedToolModel()
    result, _ = await trial(AGENT_SCENARIOS[0], model, attack=False, limits=RunLimits(max_turns=3))
    assert result.reason_codes == (ReasonCode.TURN_LIMIT_EXHAUSTED,)
    assert model.calls == 1


@pytest.mark.asyncio
async def test_malformed_tool_call_counts_as_an_attempt():
    result, _ = await trial(
        AGENT_SCENARIOS[0], ScriptedToolModel(behavior="vulnerable", malformed=True)
    )
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (ReasonCode.FORBIDDEN_TOOL_ATTEMPT,)


@pytest.mark.asyncio
async def test_call_blocked_by_the_graph_counts_as_an_attempt():
    model = ScriptedToolModel(behavior="vulnerable")

    def guarded(tools):
        allowed = [tool for tool in tools if tool.name == "fetch_document"]
        bound = model.bind_tools(tools)

        async def agent(state: MessagesState) -> dict:
            return {"messages": [await bound.ainvoke(state["messages"])]}

        def route(state: MessagesState) -> str:
            calls = getattr(state["messages"][-1], "tool_calls", None)
            return "tools" if calls and all(c["name"] == "fetch_document" for c in calls) else END

        graph = StateGraph(MessagesState)
        graph.add_node("agent", agent)
        graph.add_node("tools", ToolNode(allowed))
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", route, ["tools", END])
        graph.add_edge("tools", "agent")
        return graph.compile()

    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(harness, guarded, tool_calling=True)
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (ReasonCode.FORBIDDEN_TOOL_ATTEMPT,)


@pytest.mark.asyncio
async def test_each_trial_gets_a_thread_that_is_deleted_afterwards():
    saver = InMemorySaver()
    model = ScriptedToolModel()
    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(
        harness, lambda tools: react_graph(model, tools, saver), tool_calling=True
    )
    seen = []
    original = saver.adelete_thread

    async def spy(thread_id):
        seen.append(thread_id)
        await original(thread_id)

    saver.adelete_thread = spy  # type: ignore[method-assign]
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.outcome is Outcome.RESISTED
    assert seen == [result.trial_id]
    assert not list(saver.list({"configurable": {"thread_id": result.trial_id}}))


@pytest.mark.asyncio
async def test_async_builder_and_custom_state_mapping():
    model = ScriptedToolModel()
    seen = {}

    async def build(tools):
        return react_graph(model, tools)

    def to_input(prompt):
        seen["prompt"] = prompt
        return {"messages": [("user", prompt)]}

    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(
        harness,
        build,
        tool_calling=True,
        input_mapper=to_input,
        output_mapper=lambda state: "Report: " + message_text(state["messages"][-1]),
        config={"tags": ["wardenbot"], "configurable": {"user": "test"}},
    )
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.task_succeeded is True
    assert seen["prompt"] == AGENT_SCENARIOS[0].task


@pytest.mark.asyncio
async def test_builder_must_return_a_runnable():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(harness, lambda tools: object(), tool_calling=True)
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.outcome is Outcome.ERROR
    assert ReasonCode.TARGET_ERROR in result.reason_codes


@pytest.mark.asyncio
async def test_a_graph_that_loops_without_model_requests_stops_at_the_recursion_limit():
    def looping(tools):
        graph = StateGraph(MessagesState)
        graph.add_node("spin", lambda state: {"messages": []})
        graph.add_edge(START, "spin")
        graph.add_edge("spin", "spin")
        return graph.compile()

    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(harness, looping, tool_calling=True)
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.reason_codes == (ReasonCode.TURN_LIMIT_EXHAUSTED,)


# -- the tool-calling check --------------------------------------------------------


@pytest.mark.asyncio
async def test_probe_runs_once_per_name_and_passes_a_capable_model():
    model = ScriptedToolModel()
    for _ in range(2):
        result, _ = await trial(AGENT_SCENARIOS[0], model, tool_calling=None)
        assert result.outcome is Outcome.RESISTED
    # Two probe requests (the call, then the reply), then two per trial.
    assert model.calls == 2 + 2 * 2
    assert target_module._TOOL_CALLING["langgraph"][0] is True


@pytest.mark.asyncio
async def test_model_that_cannot_call_tools_is_unsupported():
    model = ScriptedToolModel(behavior="no_tools")
    result, _ = await trial(AGENT_SCENARIOS[2], model, tool_calling=None, name="text-only")
    assert result.outcome is Outcome.UNSUPPORTED
    assert result.reason_codes == (ReasonCode.MISSING_CAPABILITY,)
    assert model.calls == 2
    assert "2 attempts" in target_module._TOOL_CALLING["text-only"][1]


@pytest.mark.asyncio
async def test_model_that_rejects_tool_definitions_is_unsupported():
    model = ScriptedToolModel(behavior="rejects_tools")
    result, _ = await trial(AGENT_SCENARIOS[2], model, tool_calling=None)
    assert result.outcome is Outcome.UNSUPPORTED
    assert "rejected tool definitions" in target_module._TOOL_CALLING["langgraph"][1]


@pytest.mark.asyncio
async def test_probe_errors_that_are_not_about_tools_are_errors():
    def broken(tools):
        async def agent(state):
            raise ConnectionError("model server down")

        graph = StateGraph(MessagesState)
        graph.add_node("agent", agent)
        graph.add_edge(START, "agent")
        return graph.compile()

    harness = MCPHarness(AGENT_SCENARIOS[0])
    target = LangGraphAgentTarget(harness, broken)
    result = await run_scenario(target, AGENT_SCENARIOS[0], observe=harness.observe)
    assert result.outcome is Outcome.ERROR
    assert "langgraph" not in target_module._TOOL_CALLING


@pytest.mark.asyncio
async def test_tool_calling_false_is_unsupported_without_model_calls():
    model = ScriptedToolModel()
    result, _ = await trial(AGENT_SCENARIOS[0], model, tool_calling=False)
    assert result.outcome is Outcome.UNSUPPORTED
    assert model.calls == 0


# -- configuration -----------------------------------------------------------------


def test_constructor_validation():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    with pytest.raises(ValueError, match="MCPHarness"):
        LangGraphAgentTarget(object(), lambda tools: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="callable"):
        LangGraphAgentTarget(harness, "graph")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="tool_calling"):
        LangGraphAgentTarget(harness, lambda tools: None, tool_calling="yes")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="thread_id"):
        LangGraphAgentTarget(
            harness, lambda tools: None, config={"configurable": {"thread_id": "fixed"}}
        )
    capabilities = LangGraphAgentTarget(harness, lambda tools: None).capabilities
    # Input requests reach the model; the fixed tool set can't follow tool-list changes.
    assert capabilities == TrialTools.CAPABILITIES | {AgentCapability.INPUT_REQUESTS}
    assert AgentCapability.TOOL_LIST_CHANGES not in capabilities
    plain = LangGraphAgentTarget(harness, lambda tools: None, attach=False)
    assert AgentCapability.RESOURCES not in plain.capabilities


def test_default_mappers():
    from langchain_core.messages import AIMessage, HumanMessage  # type: ignore[import-not-found]

    from pytest_wardenbot.targets.langgraph import default_input, default_output

    assert default_input("hi")["messages"][0].content == "hi"
    state = {"messages": [HumanMessage("q"), AIMessage("a"), HumanMessage("again")]}
    assert default_output(state) == "a"
    assert default_output({"messages": []}) == ""
    blocks = AIMessage(content=[{"type": "text", "text": "a"}, {"type": "image"}, "b"])
    assert default_output({"messages": [blocks]}) == "ab"
    assert default_output("not a state") == ""


# -- the packaged suite --------------------------------------------------------------

CONFTEST = """
import sys
sys.path.insert(0, {root!r})

import pytest
from langgraph.graph import END, START, MessagesState, StateGraph  # type: ignore[import-not-found]
from langgraph.prebuilt import ToolNode, tools_condition  # type: ignore[import-not-found]

from pytest_wardenbot.mcp import MCPHarness
from pytest_wardenbot.targets.langgraph import LangGraphAgentTarget
from tests.fixtures.scripted_langchain_model import ScriptedToolModel

MODEL = ScriptedToolModel(behavior={behavior!r})


def build(tools):
    bound = MODEL.bind_tools(tools)

    async def agent(state):
        return {{"messages": [await bound.ainvoke(state["messages"])]}}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


@pytest.fixture
def agent_harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return MCPHarness(wardenbot_agent_scenario, attack_enabled=wardenbot_agent_attack_enabled)


@pytest.fixture
def agent_target(agent_harness):
    return LangGraphAgentTarget(agent_harness, build)


@pytest.fixture
def agent_observer(agent_harness):
    return agent_harness.observe
"""

ARGS = ("--pyargs", "pytest_wardenbot.agent_tests", "-p", "no:cacheprovider", "-p", "no:asyncio")


def configure(pytester, behavior):
    from pathlib import Path

    root = str(Path(__file__).resolve().parents[1])
    pytester.makeconftest(CONFTEST.format(root=root, behavior=behavior))


def test_packaged_suite_resistant_graph(pytester):
    configure(pytester, "resistant")
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-required")
    result.assert_outcomes(passed=16)


def test_packaged_suite_vulnerable_graph(pytester):
    configure(pytester, "vulnerable")
    result = pytester.runpytest(*ARGS)
    result.assert_outcomes(passed=8, failed=8)
    assert "Confirmed boundary violation" in result.stdout.str()


def test_packaged_suite_model_without_tools_is_skipped(pytester):
    configure(pytester, "no_tools")
    result = pytester.runpytest(*ARGS, "-rs")
    result.assert_outcomes(skipped=16)
    assert "missing_capability" in result.stdout.str()
