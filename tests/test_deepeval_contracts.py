"""Real DeepEval vendor construction and GEval HTTP, without provider calls."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from pytest_wardenbot.grading import judge


def _http_module(sdk: Any) -> Any:
    for base in sdk.DefaultHttpxClient.__mro__:
        module = base.__module__.split(".")[0]
        if module in {"httpx", "httpx2"}:
            return importlib.import_module(module)
    raise AssertionError("Provider HTTP transport changed; update the judge contract")


@pytest.fixture(params=["anthropic", "openai"])
def vendor_http(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Any:
    pytest.importorskip("deepeval")
    from deepeval import models  # type: ignore[import-not-found]
    from deepeval.config.settings import get_settings  # type: ignore[import-not-found]

    vendor = request.param
    sdk = pytest.importorskip(vendor)
    transport = _http_module(sdk)
    model_class = getattr(models, "AnthropicModel" if vendor == "anthropic" else "OpenAIModel")
    model_module = importlib.import_module(model_class.__module__)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-judge-contract")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-judge-contract")
    monkeypatch.setattr(get_settings(), "TEMPERATURE", 0.8)
    monkeypatch.setattr(get_settings(), "DEEPEVAL_MODEL_THINKING", False)
    calls: list[dict[str, Any]] = []
    clients: list[Any] = []

    def respond(request: Any) -> Any:
        assert request.url.host == "judge-contract.invalid"
        calls.append(json.loads(request.content))
        content = json.dumps(
            {
                "value": "offline-value",
                "steps": ["Compare the supplied answer with the reference."],
                "score": 9,
                "reason": "The answer agrees with the reference.",
            }
        )
        if vendor == "anthropic":
            assert request.url.path == "/v1/messages"
            body = {
                "id": "msg_judge_contract",
                "type": "message",
                "role": "assistant",
                "model": calls[-1]["model"],
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 4, "output_tokens": 5},
            }
        else:
            assert request.url.path == "/v1/chat/completions"
            body = {
                "id": "chatcmpl-judge-contract",
                "object": "chat.completion",
                "created": 1,
                "model": calls[-1]["model"],
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 5, "total_tokens": 9},
            }
        return transport.Response(200, json=body, request=request)

    sync_name = "Anthropic" if vendor == "anthropic" else "OpenAI"
    async_name = "AsyncAnthropic" if vendor == "anthropic" else "AsyncOpenAI"
    sync_class, async_class = getattr(sdk, sync_name), getattr(sdk, async_name)
    base_url = "https://judge-contract.invalid" + ("/v1" if vendor == "openai" else "")

    def sync_client(**kwargs: Any) -> Any:
        client = sync_class(
            **{
                **kwargs,
                "base_url": base_url,
                "max_retries": 0,
                "http_client": transport.Client(transport=transport.MockTransport(respond)),
            }
        )
        clients.append(client)
        return client

    def async_client(**kwargs: Any) -> Any:
        client = async_class(
            **{
                **kwargs,
                "base_url": base_url,
                "max_retries": 0,
                "http_client": transport.AsyncClient(transport=transport.MockTransport(respond)),
            }
        )
        clients.append(client)
        return client

    # Replace only constructor wiring with real SDK clients over MockTransport.
    # The actual WardenBot builder, DeepEval model, SDK requests/parsers, and
    # GEval metric remain intact. These seams cover SDKs DE imports eagerly
    # (OpenAI) and lazily (Anthropic).
    monkeypatch.setattr(sdk, sync_name, sync_client)
    monkeypatch.setattr(sdk, async_name, async_client)
    if hasattr(model_module, sync_name):
        monkeypatch.setattr(model_module, sync_name, sync_client)
        monkeypatch.setattr(model_module, async_name, async_client)
    model_name = "claude-haiku-4-5" if vendor == "anthropic" else "gpt-4o-mini"
    yield SimpleNamespace(
        vendor=vendor,
        model_name=model_name,
        calls=calls,
        clients=clients,
        native_schema=hasattr(sdk, "transform_schema"),
    )
    for client in clients:
        if inspect.iscoroutinefunction(client.close):
            asyncio.run(client.close())
        else:
            client.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_real_vendor_model_builder_and_schema_generation(
    vendor_http: Any, asynchronous: bool
) -> None:
    class Answer(BaseModel):
        value: str

    model = judge._build_deepeval_model(vendor_http.model_name, 0.2)
    try:
        output, cost = (
            await model.a_generate("Contract prompt", schema=Answer)
            if asynchronous
            else model.generate("Contract prompt", schema=Answer)
        )
        assert output.value == "offline-value"
        assert cost >= 0
        assert len(vendor_http.calls) == 1
        call = vendor_http.calls[0]
        assert call["model"] == vendor_http.model_name
        assert call["temperature"] == pytest.approx(0.2)
        assert call["messages"][0]["role"] == "user"
        if vendor_http.vendor == "anthropic":
            assert call["thinking"] == {"type": "disabled"}
            if vendor_http.native_schema:
                output_format = call["output_config"]["format"]
                assert output_format["type"] == "json_schema"
                assert output_format["schema"]["required"] == ["value"]
            else:
                assert "output_config" not in call  # SDK 0.49 uses JSON-text parsing.
    finally:
        for client in vendor_http.clients:
            if inspect.iscoroutinefunction(client.close):
                await client.close()


def test_actual_default_factory_geval_uses_real_vendor_model(vendor_http: Any) -> None:
    case = judge.semantic_equivalence_case(
        prompt="What is the answer?",
        canonical_answer="Forty-two.",
        threshold=0.7,
    )
    result = judge.judge_response(case, "Forty-two.", model_name=vendor_http.model_name)
    assert result.passed
    assert result.score == pytest.approx(0.9)
    assert "reference" in result.reason
    assert len(vendor_http.calls) >= 2  # Step generation and answer scoring.
    assert all(call["model"] == vendor_http.model_name for call in vendor_http.calls)
    assert all(call["temperature"] == 0.0 for call in vendor_http.calls)


@pytest.mark.parametrize("model_name", ["claude-haiku-4-5", "gemini-2.5-flash"])
def test_missing_vendor_model_has_actionable_upgrade_error(
    monkeypatch: pytest.MonkeyPatch,
    model_name: str,
) -> None:
    monkeypatch.setitem(sys.modules, "deepeval", SimpleNamespace(models=SimpleNamespace()))
    with pytest.raises(judge.JudgeUnavailableError, match=r"DeepEval >= 4\.2\.8"):
        judge._build_deepeval_model(model_name, 0.0)


def test_openai_builder_does_not_import_other_vendor_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    models = SimpleNamespace(OpenAIModel=lambda **kwargs: model)
    monkeypatch.setitem(sys.modules, "deepeval", SimpleNamespace(models=models))
    assert judge._build_deepeval_model("gpt-4o-mini", 0.0) is model


def test_gemini_missing_optional_sdk_has_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("deepeval")
    monkeypatch.setitem(sys.modules, "google.genai", None)
    with pytest.raises(judge.JudgeUnavailableError, match="pip install google-genai"):
        judge._build_deepeval_model("gemini-2.5-flash", 0.0)
