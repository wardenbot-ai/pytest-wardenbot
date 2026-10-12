"""Real model SDK transport and real MCP reference integration, with no paid calls."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openai")
pytest.importorskip("mcp")

from examples.mcp_agent.offline_model import OfflineModel
from examples.mcp_agent.pilot import CASES, CORPUS_DIGEST, run_pilot
from examples.mcp_agent.reference_agent import CallBudget, ResponsesMCPAgent

from pytest_wardenbot.agents import EventKind, Outcome, ReasonCode, RunLimits, run_scenario
from pytest_wardenbot.mcp import MCPHarness


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [True, False, 0, -1, float("nan"), float("inf"), "30"])
async def test_reference_rejects_invalid_deadlines_before_requests(invalid):
    simulator = OfflineModel()
    async with simulator.client() as client:
        harness = MCPHarness(CASES[0].scenario())
        with pytest.raises(ValueError, match="request_timeout"):
            ResponsesMCPAgent(
                harness, client, model="offline-response-model", request_timeout=invalid
            )
        with pytest.raises(ValueError, match="campaign_timeout"):
            await run_pilot(client, model="offline-response-model", campaign_timeout=invalid)
    assert not simulator.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["memory", "stdio", "http"])
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.split)
@pytest.mark.parametrize("profile", ["safe", "vulnerable"])
@pytest.mark.parametrize("attack", [False, True], ids=["benign", "attack"])
async def test_real_sdk_and_mcp_controls(transport, case, profile, attack):
    simulator = OfflineModel()
    client = simulator.client()
    harness = MCPHarness(
        case.scenario(),
        transport=transport,
        attack_enabled=attack,
        document_text=case.document,
        injection_text=case.injection,
    )
    target = ResponsesMCPAgent(
        harness,
        client,
        model="offline-response-model",
        profile=profile,
        expected_fact=case.expected_fact,
    )
    try:
        result = await run_scenario(target, harness.scenario, observe=harness.observe)
    finally:
        await client.close()
    assert result.task_succeeded is True
    expected = (
        Outcome.INCONCLUSIVE
        if not attack
        else Outcome.VIOLATED
        if profile == "vulnerable"
        else Outcome.RESISTED
    )
    assert result.outcome is expected
    assert harness.observe(result.trial_id).complete
    effects = [event for event in result.events if event.kind is EventKind.TOOL_EFFECT]
    assert len(effects) == (attack and profile == "vulnerable")
    if effects:
        assert effects[0].data["value"] == case.canary
    assert simulator.requests[0]["tool_choice"] == {"type": "function", "name": "fetch_document"}
    for request in simulator.requests:
        assert request["store"] is False
        assert request["max_output_tokens"] == 512
        assert request["parallel_tool_calls"] is False
        assert "previous_response_id" not in request and "conversation" not in request
        for item in request["input"]:
            if item.get("type") == "function_call":
                assert "async_" not in item
                assert "namespace" not in item  # Unset SDK defaults are not received wire fields.
                assert "caller" not in item
    document_outputs = [
        item["output"]
        for request in simulator.requests
        for item in request["input"]
        if item.get("type") == "function_call_output"
    ]
    assert any(case.document in output for output in document_outputs)
    if attack and case.surface.value == "tool_result":
        assert any(case.injection in output for output in document_outputs)
    assert client.is_closed()


@pytest.mark.asyncio
async def test_safe_dispatch_blocks_undeclared_sink_request_from_actual_model_response():
    simulator = OfflineModel()
    original = simulator.respond

    def hostile_model(request):
        response = original(request)
        body = json.loads(response.content)
        if len(simulator.requests) == 2:
            body["output"] = [simulator._call(2, "record_action", {"value": "SYNTHETIC_SECRET"})]
            return simulator.http.Response(200, json=body, request=request)
        return response

    simulator.respond = hostile_model
    client = simulator.client()
    case = CASES[0]
    harness = MCPHarness(case.scenario())
    target = ResponsesMCPAgent(harness, client, model="offline-response-model")
    try:
        result = await run_scenario(target, harness.scenario, observe=harness.observe)
    finally:
        await client.close()
    assert result.outcome is Outcome.RESISTED
    assert result.task_succeeded
    assert result.usage is not None
    assert result.usage["blocked_tool_calls"] == 1
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in result.events)
    assert not any(
        event.kind is EventKind.TOOL_CALL and event.name == "record_action"
        for event in result.events
    )


@pytest.mark.asyncio
async def test_pilot_preserves_pairs_samples_splits_and_call_budget():
    simulator = OfflineModel()
    async with simulator.client() as client:
        report = await run_pilot(client, model="offline-response-model", samples=2)
    assert report["corpus_sha256"] == CORPUS_DIGEST
    assert report["summary"]["planned"] == report["summary"]["executed"] == 16
    assert report["summary"]["outcomes"] == {"inconclusive": 8, "resisted": 4, "violated": 4}
    assert report["summary"]["model_calls"] == len(simulator.requests) == 36
    for case in CASES:
        for sample in (1, 2):
            for profile in ("safe", "vulnerable"):
                rows = [
                    row
                    for row in report["trials"]
                    if row["case_id"] == case.id
                    and row["sample"] == sample
                    and row["profile"] == profile
                ]
                assert {row["phase"] for row in rows} == {"benign", "attack"}
                assert all(row["task_succeeded"] is True for row in rows)
    exported = json.dumps(report)
    assert "WARDENBOT_PILOT_" not in exported
    assert "Ignore your task" not in exported
    assert "Document summary" not in exported
    assert "offline-synthetic-value" not in exported
    assert "resp_offline_" not in exported and "call_offline_" not in exported


@pytest.mark.asyncio
async def test_call_budget_keeps_unexecuted_trials_and_failed_trial():
    simulator = OfflineModel()
    async with simulator.client() as client:
        report = await run_pilot(client, model="offline-response-model", samples=1, max_calls=1)
    assert len(simulator.requests) == 1
    assert report["summary"]["planned"] == 8
    assert report["summary"]["outcomes"] == {"error": 1, "not_run": 7}
    assert report["summary"]["call_limit_reached"]
    assert report["trials"][0]["task_succeeded"] is None


@pytest.mark.asyncio
async def test_campaign_deadline_preserves_planned_samples_without_calls():
    simulator = OfflineModel()
    async with simulator.client() as client:
        report = await run_pilot(
            client, model="offline-response-model", samples=1, campaign_timeout=0.000001
        )
    assert report["summary"]["outcomes"].get("not_run", 0) >= 7
    assert sum(report["summary"]["outcomes"].values()) == 8
    assert not simulator.requests


@pytest.mark.asyncio
async def test_model_error_is_private_and_does_not_erase_later_trials(capfd, caplog):
    simulator = OfflineModel()
    original = simulator.respond

    def fail_first(request):
        response = original(request)
        if len(simulator.requests) == 1:
            return simulator.http.Response(
                500,
                json={
                    "error": {
                        "message": "SYNTHETIC_PRIVATE_ERROR",
                        "type": "server_error",
                        "code": "server_error",
                    }
                },
                request=request,
            )
        return response

    simulator.respond = fail_first
    async with simulator.client() as client:
        report = await run_pilot(client, model="offline-response-model", samples=1)
    assert report["summary"]["executed"] == 8
    assert report["trials"][0]["outcome"] == "error"
    assert report["trials"][0]["failure_code"] == "request_http_500"
    assert report["trials"][-1]["outcome"] == "violated"
    captured = capfd.readouterr()
    assert "SYNTHETIC_PRIVATE_ERROR" not in captured.out + captured.err + caplog.text + json.dumps(
        report
    )
    assert len(simulator.requests) == report["summary"]["model_calls"]


@pytest.mark.asyncio
async def test_mcp_startup_failure_keeps_failed_row_and_later_trials(monkeypatch):
    import pytest_wardenbot.mcp.harness as module

    original = module.build_server
    calls = 0

    def fail_first(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("SYNTHETIC_STARTUP_SECRET")
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "build_server", fail_first)
    simulator = OfflineModel()
    async with simulator.client() as client:
        report = await run_pilot(client, model="offline-response-model", samples=1)
    assert report["summary"]["planned"] == report["summary"]["executed"] == 8
    assert report["trials"][0]["outcome"] == "error"
    assert report["trials"][0]["model_calls"] == 0
    assert report["trials"][0]["protocol"] is None
    assert report["trials"][-1]["outcome"] == "violated"
    assert "SYNTHETIC_STARTUP_SECRET" not in json.dumps(report)


@pytest.mark.asyncio
async def test_nonlabel_model_metadata_is_private_and_never_formatted(capfd, caplog):
    simulator = OfflineModel()
    original = simulator.respond

    def malformed_label(request):
        response = original(request)
        body = json.loads(response.content)
        body["model"] = {"api_key": "SYNTHETIC_METADATA_SECRET"}  # pragma: allowlist secret
        return simulator.http.Response(200, json=body, request=request)

    simulator.respond = malformed_label
    async with simulator.client() as client:
        report = await run_pilot(client, model="offline-response-model", samples=1)
    assert all(row["returned_models"] == ["unreported"] for row in report["trials"])
    captured = capfd.readouterr()
    assert (
        "SYNTHETIC_METADATA_SECRET"
        not in captured.out + captured.err + caplog.text + json.dumps(report)
    )


@pytest.mark.asyncio
async def test_reference_turn_exhaustion_never_reports_resistance():
    simulator = OfflineModel()
    async with simulator.client() as client:
        harness = MCPHarness(CASES[0].scenario())
        target = ResponsesMCPAgent(
            harness, client, model="offline-response-model", profile="vulnerable"
        )
        result = await run_scenario(
            target, harness.scenario, observe=harness.observe, limits=RunLimits(max_turns=3)
        )
    assert result.outcome is Outcome.ERROR
    assert ReasonCode.TURN_LIMIT_EXHAUSTED in result.reason_codes
    assert not any(event.kind is EventKind.TOOL_EFFECT for event in result.events)


@pytest.mark.asyncio
async def test_reference_cancellation_closes_mcp_and_caller_can_close_sdk(monkeypatch):
    simulator = OfflineModel()
    client = simulator.client()
    harness = MCPHarness(CASES[0].scenario())
    target = ResponsesMCPAgent(harness, client, model="offline-response-model", budget=CallBudget())
    entered = asyncio.Event()

    async def hang(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(client.responses, "create", hang)
    task = asyncio.create_task(target.run("Summarize", trial_id="cancel-reference", max_turns=8))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client.close()
    assert client.is_closed()
    assert harness.resources["cancel-reference"].closed
    assert not harness.observe("cancel-reference").complete


def test_offline_cli_from_external_working_directory(tmp_path):
    script = Path(__file__).parents[1] / "examples" / "mcp_agent" / "run_controls.py"
    output = tmp_path / "controls.json"
    process = subprocess.run(
        [
            sys.executable,
            str(script),
            "--samples",
            "1",
            "--transport",
            "stdio",
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert not process.stdout
    assert json.loads(output.read_text())["summary"]["outcomes"] == {
        "inconclusive": 4,
        "resisted": 2,
        "violated": 2,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,answer,succeeded",
    [
        pytest.param(CASES[0], "Sales: 18%", False, id="percentage-prefix"),
        pytest.param(CASES[0], "Sales: 8%.", True, id="percentage-match"),
        pytest.param(CASES[1], "Support: 112 minutes", False, id="minutes-prefix"),
        pytest.param(CASES[1], "Support: 12 minuteslong", False, id="word-suffix"),
        pytest.param(CASES[1], "Support: 12 minutes.", True, id="minutes-match"),
    ],
)
async def test_reference_utility_requires_a_bounded_fact_not_a_numeric_substring(
    case, answer, succeeded
):
    simulator = OfflineModel()
    original = simulator.respond

    def altered_answer(request):
        response = original(request)
        body = json.loads(response.content)
        for item in body["output"]:
            if item["type"] == "message":
                item["content"][0]["text"] = answer
        return simulator.http.Response(200, json=body, request=request)

    simulator.respond = altered_answer
    harness = MCPHarness(case.scenario(), attack_enabled=False, document_text=case.document)
    async with simulator.client() as client:
        target = ResponsesMCPAgent(
            harness, client, model="offline-response-model", expected_fact=case.expected_fact
        )
        result = await run_scenario(target, case.scenario(), observe=harness.observe)
    assert result.task_succeeded is succeeded
    assert result.outcome is Outcome.INCONCLUSIVE
    assert harness.observe(result.trial_id).complete
