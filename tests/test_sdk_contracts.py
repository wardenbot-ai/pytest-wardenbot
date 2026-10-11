"""Exercise real optional SDKs against in-process HTTP transports, without API calls.

Each provider skips only when its extra is absent. The SDK CI jobs install all
extras and run this file explicitly, so missing integrations remain visible.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

import pytest

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.anthropic_msgs import (
    AnthropicMessagesAdapter,
    AsyncAnthropicMessagesAdapter,
)
from pytest_wardenbot.adapters.openai_chat import AsyncOpenAIChatAdapter, OpenAIChatAdapter


def _http_module(sdk: Any) -> Any:
    # SDKs migrated from httpx to httpx2. Use the transport family of their
    # public HTTP client; never accidentally install a real network transport.
    for base in sdk.DefaultHttpxClient.__mro__:
        name = base.__module__.split(".")[0]
        if name in {"httpx", "httpx2"}:
            return importlib.import_module(name)
    raise AssertionError("SDK HTTP transport changed; update the compatibility contract")


def _body(vendor: str) -> dict[str, Any]:
    if vendor == "openai":
        return {
            "id": "chatcmpl-contract",
            "object": "chat.completion",
            "created": 1,
            "model": "contract-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "A contract reply."},
                    "finish_reason": "stop",
                }
            ],
        }
    return {
        "id": "msg_contract",
        "type": "message",
        "role": "assistant",
        "model": "contract-model",
        "content": [{"type": "text", "text": "A contract reply."}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 4, "output_tokens": 5},
    }


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_real_sdk_default_client_constructs(vendor: str) -> None:
    sdk = pytest.importorskip(vendor)
    client_cls = sdk.OpenAI if vendor == "openai" else sdk.Anthropic
    # Construction performs no request, but catches incompatible transitive
    # HTTP-client constructor options that injected-client tests would hide.
    with client_cls(api_key="synthetic-contract-value", max_retries=0):  # pragma: allowlist secret
        pass


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_sdk_serialization_and_session_reset(vendor: str, asynchronous: bool) -> None:
    sdk = pytest.importorskip(vendor)
    transport = _http_module(sdk)
    calls: list[dict[str, Any]] = []

    def respond(request: Any) -> Any:
        assert request.url.host == "sdk-contract.invalid"
        calls.append(json.loads(request.content))
        return transport.Response(200, json=_body(vendor), request=request)

    if vendor == "openai":
        client_cls = sdk.AsyncOpenAI if asynchronous else sdk.OpenAI
    else:
        client_cls = sdk.AsyncAnthropic if asynchronous else sdk.Anthropic
    http_cls = transport.AsyncClient if asynchronous else transport.Client
    http_client = http_cls(transport=transport.MockTransport(respond))
    client = client_cls(
        api_key="synthetic-contract-value",  # pragma: allowlist secret
        base_url="https://sdk-contract.invalid/v1",
        http_client=http_client,
        max_retries=0,
    )
    if vendor == "openai":
        adapter_cls = AsyncOpenAIChatAdapter if asynchronous else OpenAIChatAdapter
    else:
        adapter_cls = AsyncAnthropicMessagesAdapter if asynchronous else AnthropicMessagesAdapter
    adapter: Any = adapter_cls(
        client=client, model="contract-model", system_prompt="Contract system."
    )

    async def exercise_async() -> None:
        first, other = await asyncio.gather(
            adapter.send_message("first", session_id="one"),
            adapter.send_message("other", session_id="two"),
        )
        assert first.text == other.text == "A contract reply."
        await adapter.send_message("followup", session_id="one")
        await adapter.reset_session("one")
        await adapter.send_message("fresh", session_id="one")
        await client.close()

    try:
        if asynchronous:
            asyncio.run(exercise_async())
        else:
            assert adapter.send_message("first", session_id="one").text == "A contract reply."
            assert adapter.send_message("other", session_id="two").text == "A contract reply."
            adapter.send_message("followup", session_id="one")
            adapter.reset_session("one")
            adapter.send_message("fresh", session_id="one")
    finally:
        if not asynchronous:
            client.close()
    by_last_prompt = {call["messages"][-1]["content"]: call for call in calls}
    assert [
        m["content"] for m in by_last_prompt["followup"]["messages"] if m["role"] == "user"
    ] == [
        "first",
        "followup",
    ]
    for prompt in ("other", "fresh"):
        assert [
            m["content"] for m in by_last_prompt[prompt]["messages"] if m["role"] == "user"
        ] == [prompt]
    assert len(calls) == 4


@pytest.mark.parametrize("vendor", ["openai", "anthropic"])
def test_real_sdk_error_wrapping(vendor: str) -> None:
    sdk = pytest.importorskip(vendor)
    transport = _http_module(sdk)

    def respond(request: Any) -> Any:
        return transport.Response(
            429,
            json={"error": {"type": "rate_limit_error", "message": "contract rate limit"}},
            request=request,
        )

    client_cls = sdk.OpenAI if vendor == "openai" else sdk.Anthropic
    adapter_cls = OpenAIChatAdapter if vendor == "openai" else AnthropicMessagesAdapter
    with client_cls(
        api_key="synthetic-contract-value",  # pragma: allowlist secret
        base_url="https://sdk-contract.invalid/v1",
        http_client=transport.Client(transport=transport.MockTransport(respond)),
        max_retries=0,
    ) as client:
        adapter = adapter_cls(client=client, model="contract-model")
        with pytest.raises(WardenBotInfraError, match="rate_limit"):
            adapter.send_message("hello")


def test_real_langchain_runnable_contract() -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.runnables import RunnableLambda  # type: ignore[import-not-found]

    from pytest_wardenbot.adapters.langchain_runnable import (
        AsyncLangChainAdapter,
        LangChainAdapter,
    )

    def echo(prompt: str) -> dict[str, str]:
        return {"answer": "Echo: " + prompt}

    runnable = RunnableLambda(echo)
    assert LangChainAdapter(runnable).send_message("hello").text == "Echo: hello"
    response = asyncio.run(AsyncLangChainAdapter(runnable).send_message("async"))
    assert response.text == "Echo: async"


def test_real_deepeval_metric_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
    monkeypatch.setenv("DEEPEVAL_UPDATE_WARNING_OPT_OUT", "YES")
    pytest.importorskip("deepeval")
    from deepeval.models.base_model import DeepEvalBaseLLM  # type: ignore[import-not-found]

    from pytest_wardenbot.grading import judge

    class OfflineJudge(DeepEvalBaseLLM):
        def load_model(self) -> None:
            return None

        def get_model_name(self) -> str:
            return "offline-contract"

        def generate(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
            payload = {
                "steps": ["Compare the supplied answer with the reference."],
                "score": 9,
                "reason": "The supplied answer agrees with the reference.",
            }
            return schema(**payload) if schema is not None else json.dumps(payload)

        async def a_generate(self, prompt: str, schema: Any = None, **kwargs: Any) -> Any:
            return self.generate(prompt, schema=schema, **kwargs)

    offline = OfflineJudge()
    monkeypatch.setattr(judge, "_build_deepeval_model", lambda *_args: offline)
    case = judge.semantic_equivalence_case(
        prompt="What is the answer?", canonical_answer="Forty-two.", threshold=0.7
    )
    result = judge.judge_response(case, "Forty-two.")
    assert result.passed
    assert result.score == pytest.approx(0.9)
    assert "reference" in result.reason
