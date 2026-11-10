"""TrialTools: the framework-neutral bookkeeping every application target needs."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents import (
    AgentCapability,
    AttackSurface,
    CapabilityUnavailable,
    EventKind,
    Outcome,
    ReasonCode,
    RunLimits,
    Scenario,
    run_scenario,
)
from pytest_wardenbot.agents.evaluation import required_capabilities
from pytest_wardenbot.agents.scenarios import AGENT_SCENARIOS
from pytest_wardenbot.mcp import MCPHarness, ToolSpec, TrialTools, TurnLimitReached
from pytest_wardenbot.mcp._server import DOCUMENT_TOOL, SINK_TOOL


class Scripted:
    """A deterministic agent loop driven by a plan of model steps."""

    name = "scripted-trial-tools"
    capabilities = TrialTools.CAPABILITIES

    def __init__(self, harness, plan, **options):
        self.harness = harness
        self.plan = plan
        self.options = options
        self.outputs: list[str] = []
        self.prompt = ""

    async def reset(self, trial_id):
        pass

    async def run(self, task, *, trial_id, max_turns):
        async with TrialTools(self.harness, trial_id, max_turns=max_turns, **self.options) as tools:
            self.prompt = tools.prompt(task)
            for step, *args in self.plan:
                tools.turn()
                if step == "call":
                    self.outputs.append(await tools.call(*args))
                elif step == "request":
                    tools.requested(*args)
                elif step == "answer":
                    tools.answer(args[0])
                    break
        return tools.result()


def payload(scenario):
    return {"value": scenario.canary or "anything"}


async def trial(scenario, plan, *, attack=True, limits=None, **options):
    harness = MCPHarness(scenario, attack_enabled=attack)
    target = Scripted(harness, plan, **options)
    result = await run_scenario(target, scenario, observe=harness.observe, limits=limits)
    return result, target, harness


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", AGENT_SCENARIOS, ids=lambda case: case.id)
async def test_resisting_agent_resists_and_completes_the_task(scenario):
    result, target, _ = await trial(
        scenario, [("call", DOCUMENT_TOOL, {}), ("answer", "Sales rose 8%.")]
    )
    assert result.outcome is Outcome.RESISTED
    assert result.reason_codes == (ReasonCode.BOUNDARY_HELD,)
    assert result.task_succeeded is True
    if scenario.surface in (AttackSurface.RESOURCE, AttackSurface.PROMPT):
        assert "Ignore your task" in target.prompt
    else:
        assert target.prompt == scenario.task


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", AGENT_SCENARIOS, ids=lambda case: case.id)
async def test_obeying_agent_violates_with_an_effect(scenario):
    result, _, _ = await trial(
        scenario,
        [("call", DOCUMENT_TOOL, {}), ("call", SINK_TOOL, payload(scenario)), ("answer", "8%")],
    )
    expected = (
        ReasonCode.FORBIDDEN_TOOL_EFFECT if scenario.forbidden_tool else ReasonCode.CANARY_LEAK
    )
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (expected,)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", AGENT_SCENARIOS, ids=lambda case: case.id)
async def test_requested_call_that_never_ran_counts_as_an_attempt(scenario):
    result, _, _ = await trial(
        scenario,
        [("call", DOCUMENT_TOOL, {}), ("request", SINK_TOOL, payload(scenario)), ("answer", "8%")],
    )
    expected = (
        ReasonCode.FORBIDDEN_TOOL_ATTEMPT
        if scenario.forbidden_tool
        else ReasonCode.CANARY_LEAK_ATTEMPT
    )
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (expected,)


@pytest.mark.asyncio
async def test_requested_and_dispatched_call_is_recorded_once():
    scenario = AGENT_SCENARIOS[0]
    harness = MCPHarness(scenario)
    async with TrialTools(harness, "once", max_turns=10) as tools:
        tools.requested(SINK_TOOL, '{"value": "x"}')
        await tools.call(SINK_TOOL, {"value": "x"})
        tools.requested(DOCUMENT_TOOL, None)
        await tools.call(DOCUMENT_TOOL, "")
    calls = [event for event in harness.observe("once").events if event.kind is EventKind.TOOL_CALL]
    assert [(event.name, event.data.get("blocked")) for event in calls] == [
        (SINK_TOOL, None),
        (DOCUMENT_TOOL, None),
    ]


@pytest.mark.asyncio
async def test_malformed_arguments_are_blocked_attempts_and_reported_to_the_model():
    scenario = AGENT_SCENARIOS[0]
    harness = MCPHarness(scenario)
    outputs = []
    async with TrialTools(harness, "malformed", max_turns=10) as tools:
        outputs.append(await tools.call(SINK_TOOL, '{"value": '))
        outputs.append(await tools.call(SINK_TOOL, "[1, 2]"))
    assert outputs == ["Error: tool arguments must be a JSON object."] * 2
    events = harness.observe("malformed").events
    assert [(event.name, event.data["blocked"]) for event in events] == [
        (SINK_TOOL, True),
        (SINK_TOOL, True),
    ]
    assert events[0].data["arguments"] == '{"value": '


@pytest.mark.asyncio
async def test_canary_in_an_unknown_tool_call_is_a_leak_attempt():
    scenario = AGENT_SCENARIOS[1]
    assert scenario.canary
    result, target, _ = await trial(
        scenario,
        [
            ("call", DOCUMENT_TOOL, {}),
            ("call", "send_email", {"body": scenario.canary}),
            ("answer", "8%"),
        ],
    )
    assert target.outputs[1] == "Error: unknown tool 'send_email'."
    assert result.reason_codes == (ReasonCode.CANARY_LEAK_ATTEMPT,)


@pytest.mark.asyncio
async def test_unexposed_harness_tool_is_hidden_and_blocked():
    scenario = AGENT_SCENARIOS[0]
    harness = MCPHarness(scenario)
    async with TrialTools(harness, "expose", max_turns=10, expose={DOCUMENT_TOOL}) as tools:
        assert [spec.name for spec in tools.specs] == [DOCUMENT_TOOL]
        output = await tools.call(SINK_TOOL, {"value": "x"})
    assert output == f"Error: tool {SINK_TOOL!r} is not available."
    events = harness.observe("expose").events
    assert [event.data.get("blocked") for event in events if event.name == SINK_TOOL] == [True]
    assert not [event for event in events if event.kind is EventKind.TOOL_EFFECT]


@pytest.mark.asyncio
async def test_tool_errors_come_back_as_text():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    async with TrialTools(harness, "errors", max_turns=10) as tools:
        output = await tools.call(SINK_TOOL, {})
    assert output.startswith("Error: ")
    # The harness saw the attempt with invalid arguments; no effect happened.
    kinds = [event.kind for event in harness.observe("errors").events]
    assert kinds == [EventKind.TOOL_CALL]


@pytest.mark.asyncio
async def test_turn_limit_stops_the_loop_and_counts_the_blocked_call():
    scenario = AGENT_SCENARIOS[0]
    result, _, _ = await trial(
        scenario,
        [("call", DOCUMENT_TOOL, {}), ("call", SINK_TOOL, {"value": "x"}), ("answer", "8%")],
        limits=RunLimits(max_turns=4),
    )
    # discovery, model, fetch, model; the sink dispatch had no turn left.
    assert result.outcome is Outcome.VIOLATED
    assert result.reason_codes == (
        ReasonCode.FORBIDDEN_TOOL_ATTEMPT,
        ReasonCode.TURN_LIMIT_EXHAUSTED,
    )
    assert result.turns == 4


@pytest.mark.asyncio
async def test_finishing_on_the_last_turn_is_not_exhaustion():
    result, _, _ = await trial(
        AGENT_SCENARIOS[0],
        [("call", DOCUMENT_TOOL, {}), ("answer", "8%")],
        limits=RunLimits(max_turns=4),
    )
    assert result.outcome is Outcome.RESISTED
    assert result.turns == 4


@pytest.mark.asyncio
async def test_no_turns_for_discovery_means_exhausted_without_exposure():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    async with TrialTools(harness, "zero", max_turns=0) as tools:
        assert tools.specs == ()
        tools.turn()
    run = tools.result()
    assert run.limit_exhausted is True
    assert run.turns == 0
    assert run.task_succeeded is False
    assert harness.observe("zero").complete


@pytest.mark.asyncio
async def test_attach_false_reads_nothing_and_declares_tool_capabilities():
    scenario = next(case for case in AGENT_SCENARIOS if case.surface is AttackSurface.RESOURCE)
    harness = MCPHarness(scenario)
    async with TrialTools(harness, "plain", max_turns=10, attach=False) as tools:
        assert tools.prompt("Task") == "Task"
    assert harness.observe("plain").events == ()
    assert not required_capabilities(scenario) <= TrialTools.TOOL_CAPABILITIES
    assert required_capabilities(scenario) <= TrialTools.CAPABILITIES


@pytest.mark.asyncio
async def test_baseline_is_valid_without_exposure():
    result, _, _ = await trial(
        AGENT_SCENARIOS[0], [("call", DOCUMENT_TOOL, {}), ("answer", "8%")], attack=False
    )
    assert result.outcome is Outcome.INCONCLUSIVE
    assert result.reason_codes == (ReasonCode.MISSING_EXPOSURE,)
    assert result.task_succeeded is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "document", "succeeded"),
    [
        ("Sales rose 8%.", True, True),
        ("Up 8 percent.", True, True),
        ("Up 18%.", True, False),
        ("Sales rose 8%.", False, False),
    ],
)
async def test_task_success_needs_the_document_and_the_fact(answer, document, succeeded):
    harness = MCPHarness(AGENT_SCENARIOS[0])
    async with TrialTools(harness, "fact", max_turns=10) as tools:
        if document:
            await tools.call(DOCUMENT_TOOL, {})
        tools.answer(answer)
    assert tools.result().task_succeeded is succeeded


def test_custom_document_requires_a_task_check():
    harness = MCPHarness(AGENT_SCENARIOS[0], document_text="Churn fell to 2%.")
    with pytest.raises(ValueError, match="task_check"):
        TrialTools(harness, "custom", max_turns=5)
    TrialTools(harness, "custom", max_turns=5, task_check=lambda text: "2%" in text)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"max_turns": -1}, "max_turns"), ({"max_turns": True}, "max_turns")],
)
def test_constructor_validation(kwargs, message):
    with pytest.raises(ValueError, match=message):
        TrialTools(MCPHarness(AGENT_SCENARIOS[0]), "bad", **kwargs)
    with pytest.raises(ValueError, match="MCPHarness"):
        TrialTools(object(), "bad", max_turns=1)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_tool_formats_and_usage():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    async with TrialTools(harness, "formats", max_turns=10) as tools:
        names = [spec.name for spec in tools.specs]
        assert isinstance(tools.specs[0], ToolSpec)
        assert [tool["function"]["name"] for tool in tools.openai_tools()] == names
        assert tools.openai_tools()[0]["type"] == "function"
        assert [tool["name"] for tool in tools.anthropic_tools()] == names
        assert all("input_schema" in tool for tool in tools.anthropic_tools())
        tools.record_usage({"input_tokens": 5, "bad": -1, "flag": True})
        tools.record_usage({"input_tokens": 2})
        tools.answer(None)
    assert tools.result().usage == {"input_tokens": 7}
    assert tools.result().final_text == ""


@pytest.mark.asyncio
async def test_misuse_outside_the_context_is_an_error():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    tools = TrialTools(harness, "misuse", max_turns=5)
    with pytest.raises(RuntimeError, match="async with"):
        tools.turn()
    async with tools:
        pass
    with pytest.raises(RuntimeError, match="async with"):
        await tools.call(DOCUMENT_TOOL, {})
    with pytest.raises(RuntimeError, match="once"):
        async with tools:
            pass


@pytest.mark.asyncio
async def test_other_exceptions_propagate_and_leave_an_incomplete_trace():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    with pytest.raises(WardenBotInfraError):
        async with TrialTools(harness, "boom", max_turns=5) as tools:
            await tools.call(DOCUMENT_TOOL, {})
            raise RuntimeError("model client failed")
    assert harness.observe("boom").complete is False


@pytest.mark.asyncio
async def test_turn_limit_reached_is_suppressed_only_by_the_session():
    harness = MCPHarness(AGENT_SCENARIOS[0])
    async with TrialTools(harness, "limit", max_turns=1) as tools:
        with pytest.raises(TurnLimitReached):
            tools.turn()
        tools.turn()
    assert tools.result().limit_exhausted is True


# -- run-time capability checks ------------------------------------------------


class NoTools:
    name = "no-tools"
    capabilities = TrialTools.CAPABILITIES

    def __init__(
        self,
        harness: MCPHarness | None = None,
        capability=AgentCapability.TOOL_CALLS,
        violate=False,
    ):
        self.harness = harness
        self.capability = capability
        self.violate = violate

    async def reset(self, trial_id):
        pass

    async def run(self, task, *, trial_id, max_turns):
        if self.violate:
            assert self.harness is not None
            async with TrialTools(self.harness, trial_id, max_turns=max_turns) as tools:
                await tools.call(SINK_TOOL, {"value": "x"})
        raise CapabilityUnavailable(self.capability)


@pytest.mark.asyncio
async def test_capability_unavailable_is_unsupported_not_resisted():
    scenario = AGENT_SCENARIOS[2]
    harness = MCPHarness(scenario)
    seen = []
    result = await run_scenario(
        NoTools(), scenario, observe=harness.observe, on_error=lambda r, e: seen.append(r)
    )
    assert result.outcome is Outcome.UNSUPPORTED
    assert result.reason_codes == (ReasonCode.MISSING_CAPABILITY,)
    assert seen == [ReasonCode.MISSING_CAPABILITY]


@pytest.mark.asyncio
async def test_recorded_violation_beats_a_late_capability_report():
    scenario = AGENT_SCENARIOS[0]
    harness = MCPHarness(scenario)
    result = await run_scenario(NoTools(harness, violate=True), scenario, observe=harness.observe)
    assert result.outcome is Outcome.VIOLATED


@pytest.mark.asyncio
async def test_capability_the_scenario_does_not_need_is_a_target_error():
    scenario = AGENT_SCENARIOS[0]
    result = await run_scenario(NoTools(capability=AgentCapability.MEMORY), scenario)
    assert result.outcome is Outcome.ERROR
    assert result.reason_codes == (ReasonCode.TARGET_ERROR,)


@pytest.mark.asyncio
async def test_capability_unavailable_without_observer_is_unsupported():
    scenario = Scenario(
        id="probe", version="1", task="t", surface=AttackSurface.TOOL_RESULT, forbidden_tool="x"
    )
    result = await run_scenario(NoTools(capability=AgentCapability.TOOL_RESULTS), scenario)
    assert result.outcome is Outcome.UNSUPPORTED


def test_capability_unavailable_requires_a_capability():
    with pytest.raises(ValueError, match="AgentCapability"):
        CapabilityUnavailable("tool_calls")  # type: ignore[arg-type]
    assert str(CapabilityUnavailable(AgentCapability.TOOL_CALLS)) == (
        "Capability unavailable: tool_calls"
    )


@pytest.mark.asyncio
async def test_record_blocked_call_keeps_unserializable_arguments():
    harness = MCPHarness(AGENT_SCENARIOS[1])
    async with harness.trial("raw") as client:
        client.record_blocked_call(SINK_TOOL, {"value": float("nan")})
        client.record_blocked_call(SINK_TOOL, {1: AGENT_SCENARIOS[1].canary})
        with pytest.raises(ValueError, match="tool name"):
            client.record_blocked_call("", {})
    events = harness.observe("raw").events
    assert [event.data["blocked"] for event in events] == [True, True]
    assert events[0].data["arguments"] == '{"value": NaN}'
    assert str(AGENT_SCENARIOS[1].canary) in str(events[1].data["arguments"])
