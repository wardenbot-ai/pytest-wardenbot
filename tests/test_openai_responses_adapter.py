"""Responses contracts, including real SDK transports without API calls."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pytest_wardenbot import AsyncChatbotAdapter, ChatbotAdapter, WardenBotInfraError
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.openai_responses import (
    AsyncOpenAIResponsesAdapter,
    OpenAIResponsesAdapter,
)

pytest_plugins = ["pytester"]


def _body(text: str = "Safe reply.") -> dict[str, Any]:
    return {
        "id": "resp_contract",
        "object": "response",
        "created_at": 1,
        "model": "contract-model",
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {
                "id": "rs_contract",
                "type": "reasoning",
                "summary": [],
                "encrypted_content": "encrypted-reasoning-contract",
            },
            {
                "id": "msg_contract",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
        ],
    }


class _Response:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "json"
        return self.raw  # Deliberately aliased; adapter must take its own copy.

    def __repr__(self) -> str:
        return "sensitive-response-body-that-must-not-leak"


class _Client:
    def __init__(self, *, asynchronous: bool, replies: list[Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.replies = list(replies or [_Response(_body())])
        self.closed = 0
        self.responses = SimpleNamespace(create=self._acreate if asynchronous else self._create)
        self.close = self._aclose if asynchronous else self._close

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def _acreate(self, **kwargs: Any) -> Any:
        return self._create(**kwargs)

    def _close(self) -> None:
        self.closed += 1

    async def _aclose(self) -> None:
        self._close()


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def asynchronous(request: pytest.FixtureRequest) -> bool:
    return bool(request.param)


def _adapter(asynchronous: bool, client: Any, **kwargs: Any) -> Any:
    cls = AsyncOpenAIResponsesAdapter if asynchronous else OpenAIResponsesAdapter
    return cls(client=client, **kwargs)


async def _send(adapter: Any, prompt: str, session_id: str | None = None) -> Any:
    result = adapter.send_message(prompt, session_id=session_id)
    return await result if inspect.isawaitable(result) else result


async def _reset(adapter: Any, session_id: str) -> None:
    result = adapter.reset_session(session_id)
    if inspect.isawaitable(result):
        await result


async def _close(adapter: Any, asynchronous: bool) -> None:
    if asynchronous:
        await adapter.aclose()
    else:
        adapter.close()


def test_protocol_and_injected_client_never_imports_sdk(
    asynchronous: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    adapter = _adapter(asynchronous, _Client(asynchronous=asynchronous))
    assert isinstance(adapter, AsyncChatbotAdapter if asynchronous else ChatbotAdapter)
    assert getattr(adapter, "stateful", False) is True


@pytest.mark.asyncio
async def test_requests_preserve_instructions_full_output_and_isolated_sessions(
    asynchronous: bool,
) -> None:
    client = _Client(asynchronous=asynchronous)
    adapter = _adapter(asynchronous, client, model="chosen-model", system_prompt="Account support.")
    first = await _send(adapter, "one", "")
    await _send(adapter, "other", "other")
    await _send(adapter, "two", "")
    await _send(adapter, "stateless")
    await _send(adapter, "stateless-again")
    assert first.text == "Safe reply."
    assert first.latency_ms is not None and first.latency_ms >= 0
    assert all(call["model"] == "chosen-model" for call in client.calls)
    assert all(call["instructions"] == "Account support." for call in client.calls)
    assert all(call["store"] is False for call in client.calls)
    assert all(call["include"] == ["reasoning.encrypted_content"] for call in client.calls)
    assert all("temperature" not in call for call in client.calls)
    assert all(
        "previous_response_id" not in call and "conversation" not in call for call in client.calls
    )
    assert client.calls[2]["input"] == [
        {"role": "user", "content": "one"},
        *_body()["output"],
        {"role": "user", "content": "two"},
    ]
    for index, prompt in ((1, "other"), (3, "stateless"), (4, "stateless-again")):
        assert client.calls[index]["input"] == [{"role": "user", "content": prompt}]
    await _reset(adapter, "")
    await _send(adapter, "fresh", "")
    assert client.calls[-1]["input"] == [{"role": "user", "content": "fresh"}]


@pytest.mark.asyncio
async def test_optional_fields_are_copied_and_output_history_is_not_aliased(
    asynchronous: bool,
) -> None:
    raw = _body()
    extras = {
        "max_output_tokens": 256,
        "metadata": {"run": "original"},
        "include": ["message.output_text.logprobs", "reasoning.encrypted_content"],
    }
    client = _Client(asynchronous=asynchronous, replies=[_Response(raw)])
    adapter = _adapter(asynchronous, client, temperature=0.2, extra_request_fields=extras)
    extras["metadata"]["run"] = "changed"
    first = await _send(adapter, "first", "s")
    assert "instructions" not in client.calls[0]
    assert client.calls[0]["temperature"] == 0.2
    assert client.calls[0]["max_output_tokens"] == 256
    assert client.calls[0]["metadata"] == {"run": "original"}
    assert client.calls[0]["include"] == [
        "reasoning.encrypted_content",
        "message.output_text.logprobs",
    ]
    raw["output"][0]["encrypted_content"] = "mutated-sdk-object"
    assert first.raw is not None
    first.raw["output"][1]["content"][0]["text"] = "mutated-public-response"
    client.calls[0]["metadata"]["run"] = "mutated-sdk-request"
    await _send(adapter, "second", "s")
    second_input = client.calls[-1]["input"]
    assert second_input[1]["encrypted_content"] == "encrypted-reasoning-contract"
    assert second_input[2]["content"][0]["text"] == "Safe reply."
    assert client.calls[-1]["metadata"] == {"run": "original"}
    second_input[1]["encrypted_content"] = "mutated-sdk-history-input"
    await _send(adapter, "third", "s")
    assert client.calls[-1]["input"][1]["encrypted_content"] == "encrypted-reasoning-contract"


@pytest.mark.parametrize(
    "field",
    [
        "model",
        "input",
        "instructions",
        "temperature",
        "store",
        "session_id",
        "previous_response_id",
        "conversation",
        "stream",
        "stream_options",
        "background",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "max_tool_calls",
        "prompt",
        "extra_body",
    ],
)
def test_reserved_extras_are_rejected_before_creating_a_client(
    field: str,
    asynchronous: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    cls = AsyncOpenAIResponsesAdapter if asynchronous else OpenAIResponsesAdapter
    with pytest.raises(ValueError, match="reserved"):
        cls(extra_request_fields={field: "sensitive-value"})


@pytest.mark.parametrize("include", ["reasoning.encrypted_content", [7], None])
def test_malformed_include_is_rejected(asynchronous: bool, include: Any) -> None:
    with pytest.raises(ValueError, match="include"):
        _adapter(
            asynchronous,
            _Client(asynchronous=asynchronous),
            extra_request_fields={"include": include},
        )


@pytest.mark.asyncio
async def test_refusal_and_multiple_messages_are_read_from_output(asynchronous: bool) -> None:
    raw = _body()
    raw["output"][1]["content"] = [{"type": "refusal", "refusal": "I cannot help."}]
    second = deepcopy(raw["output"][1])
    second["id"] = "msg_second"
    second["content"] = [
        {"type": "output_text", "text": " Try account support.", "annotations": []}
    ]
    raw["output"].append(second)
    adapter = _adapter(asynchronous, _Client(asynchronous=asynchronous, replies=[_Response(raw)]))
    assert (await _send(adapter, "hi")).text == "I cannot help. Try account support."


def _invalid_bodies() -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    for status in ("incomplete", "failed", "in_progress", "queued", "cancelled", None):
        raw = _body()
        raw["status"] = status
        invalid.append(raw)
    for field in ("error", "incomplete_details"):
        raw = _body()
        raw[field] = {"message": "sensitive-response-body-that-must-not-leak"}
        invalid.append(raw)
    for output in ([], None, "sensitive-response-body-that-must-not-leak"):
        raw = _body()
        raw["output"] = output
        invalid.append(raw)
    for kind in ("function_call", "web_search_call", "file_search_call", "unknown"):
        raw = _body()
        raw["output"].append({"id": "tool", "type": kind})
        invalid.append(raw)
    for field, value in (
        ("status", "incomplete"),
        ("role", "user"),
        ("id", None),
        ("content", []),
        ("content", [{}]),
        ("content", [7]),
        ("content", [{"type": "output_text", "text": None}]),
        ("content", [{"type": "refusal", "refusal": 7}]),
        ("content", [{"type": "output_audio", "text": "partial text"}]),
        ("content", [{"type": "output_text", "text": ""}]),
    ):
        raw = _body()
        raw["output"][1][field] = value
        invalid.append(raw)
    raw = _body()
    raw["output"][0]["status"] = "in_progress"
    invalid.append(raw)
    for field, value in (
        ("summary", [None]),
        ("summary", [{"type": "summary_text", "text": 7}]),
        ("encrypted_content", 7),
    ):
        raw = _body()
        raw["output"][0][field] = value
        invalid.append(raw)
    raw = _body()
    raw["output"] = raw["output"][:1]  # Reasoning alone is not an answer.
    invalid.append(raw)
    return invalid


@pytest.mark.parametrize("raw", _invalid_bodies())
@pytest.mark.asyncio
async def test_invalid_responses_are_infrastructure_errors_without_history_commit(
    raw: dict[str, Any],
    asynchronous: bool,
) -> None:
    client = _Client(asynchronous=asynchronous, replies=[_Response(raw), _Response(_body())])
    adapter = _adapter(asynchronous, client)
    with pytest.raises(WardenBotInfraError) as error:
        await _send(adapter, "rejected", "s")
    assert "sensitive-response-body-that-must-not-leak" not in str(error.value)
    await _send(adapter, "valid", "s")
    assert client.calls[-1]["input"] == [{"role": "user", "content": "valid"}]


@pytest.mark.asyncio
async def test_sdk_errors_do_not_expose_secrets_or_poison_existing_history(
    asynchronous: bool,
) -> None:
    client = _Client(
        asynchronous=asynchronous,
        replies=[
            _Response(_body()),
            RuntimeError("api_key=sk-sensitive-response-body"),
            _Response(_body()),
        ],
    )
    adapter = _adapter(asynchronous, client)
    await _send(adapter, "priming", "s")
    with pytest.raises(WardenBotInfraError, match="RuntimeError") as error:
        await _send(adapter, "failed", "s")
    rendered = "".join(traceback.format_exception(error.value))
    assert "sk-sensitive" not in rendered
    await _send(adapter, "next", "s")
    assert client.calls[-1]["input"] == [
        {"role": "user", "content": "priming"},
        *_body()["output"],
        {"role": "user", "content": "next"},
    ]


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.asyncio
async def test_redaction_and_opt_out_do_not_mutate_sdk_payload(
    asynchronous: bool, keep: bool
) -> None:
    raw = _body()
    raw["metadata"] = {"api_key": "synthetic-secret"}  # pragma: allowlist secret
    adapter = _adapter(
        asynchronous,
        _Client(asynchronous=asynchronous, replies=[_Response(raw)]),
        keep_sensitive_response_fields=keep,
    )
    result = await _send(adapter, "hi")
    assert result.raw is not None
    assert result.raw["metadata"]["api_key"] == ("synthetic-secret" if keep else "[REDACTED]")
    assert result.raw["output"][0]["encrypted_content"] == (
        "encrypted-reasoning-contract" if keep else "[REDACTED]"
    )
    assert raw["metadata"]["api_key"] == "synthetic-secret"  # pragma: allowlist secret
    assert raw["output"][0]["encrypted_content"] == "encrypted-reasoning-contract"


def test_missing_extra_and_old_client_have_clear_errors(
    asynchronous: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cls = AsyncOpenAIResponsesAdapter if asynchronous else OpenAIResponsesAdapter
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match=r"SDK >= 1.66.3.*pytest-wardenbot\[openai\]"):
        cls()
    old_sdk = SimpleNamespace(
        OpenAI=lambda: SimpleNamespace(), AsyncOpenAI=lambda: SimpleNamespace()
    )
    monkeypatch.setitem(sys.modules, "openai", old_sdk)
    with pytest.raises(ImportError, match=r"SDK >= 1\.66\.3"):
        cls()
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace())
    with pytest.raises(ImportError, match=r"SDK >= 1\.66\.3"):
        cls()
    with pytest.raises(ValueError, match=r"responses\.create"):
        cls(client=SimpleNamespace())


@pytest.mark.asyncio
async def test_client_ownership_on_close(
    asynchronous: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned = _Client(asynchronous=asynchronous)
    sdk = SimpleNamespace(OpenAI=lambda: owned, AsyncOpenAI=lambda: owned)
    monkeypatch.setitem(sys.modules, "openai", sdk)
    cls = AsyncOpenAIResponsesAdapter if asynchronous else OpenAIResponsesAdapter
    adapter = cls()
    await _close(adapter, asynchronous)
    assert owned.closed == 1
    injected = _Client(asynchronous=asynchronous)
    adapter = cls(client=injected)
    await _close(adapter, asynchronous)
    assert injected.closed == 0


def test_sync_same_session_serializes_and_other_sessions_remain_parallel() -> None:
    started, release = threading.Event(), threading.Event()
    client = _Client(asynchronous=False)
    original = client.responses.create

    def create(**kwargs: Any) -> Any:
        if kwargs["input"][-1]["content"] == "first":
            started.set()
            assert release.wait(5), "Test did not release the first call"
        return original(**kwargs)

    client.responses.create = create
    adapter = OpenAIResponsesAdapter(client=client)
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(adapter.send_message, "first", session_id="s")
        try:
            assert started.wait(5)
            second = pool.submit(adapter.send_message, "second", session_id="s")
            other = pool.submit(adapter.send_message, "other", session_id="other")
            assert other.result(timeout=5).text == "Safe reply."
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=5)
        second.result(timeout=5)
    assert client.calls[-1]["input"] == [
        {"role": "user", "content": "first"},
        *_body()["output"],
        {"role": "user", "content": "second"},
    ]
    adapter.reset_session("s")
    adapter.reset_session("other")
    assert adapter._sessions._states == {}


def test_sync_reset_waits_for_inflight_call_and_then_clears_history() -> None:
    started, release, reset_started = threading.Event(), threading.Event(), threading.Event()
    client = _Client(asynchronous=False)
    original = client.responses.create

    def create(**kwargs: Any) -> Any:
        if kwargs["input"][-1]["content"] == "first":
            started.set()
            assert release.wait(5), "Test did not release the first call"
        return original(**kwargs)

    client.responses.create = create
    adapter = OpenAIResponsesAdapter(client=client)

    def reset() -> None:
        reset_started.set()
        adapter.reset_session("")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(adapter.send_message, "first", session_id="")
        try:
            assert started.wait(5)
            resetting = pool.submit(reset)
            assert reset_started.wait(5)
            assert not resetting.done()
        finally:
            release.set()
        first.result(timeout=5)
        resetting.result(timeout=5)
    assert adapter._sessions._states == {}
    adapter.send_message("following", session_id="")
    assert client.calls[-1]["input"] == [{"role": "user", "content": "following"}]


@pytest.mark.asyncio
async def test_async_same_session_serializes_and_other_sessions_remain_parallel() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    client = _Client(asynchronous=True)
    original = client.responses.create

    async def create(**kwargs: Any) -> Any:
        if kwargs["input"][-1]["content"] == "first":
            started.set()
            await release.wait()
        return await original(**kwargs)

    client.responses.create = create
    adapter = AsyncOpenAIResponsesAdapter(client=client)
    first = asyncio.create_task(adapter.send_message("first", session_id="s"))
    try:
        await asyncio.wait_for(started.wait(), 5)
        second = asyncio.create_task(adapter.send_message("second", session_id="s"))
        other = await asyncio.wait_for(adapter.send_message("other", session_id="other"), 5)
        assert other.text == "Safe reply."
        assert not second.done()
    finally:
        release.set()
    await asyncio.gather(first, second)
    assert client.calls[-1]["input"] == [
        {"role": "user", "content": "first"},
        *_body()["output"],
        {"role": "user", "content": "second"},
    ]
    await adapter.reset_session("s")
    await adapter.reset_session("other")
    assert adapter._sessions._states == {}


@pytest.mark.asyncio
async def test_async_reset_waits_and_queued_send_starts_a_fresh_conversation() -> None:
    started, release = asyncio.Event(), asyncio.Event()
    client = _Client(asynchronous=True)
    original = client.responses.create

    async def create(**kwargs: Any) -> Any:
        if kwargs["input"][-1]["content"] == "first":
            started.set()
            await release.wait()
        return await original(**kwargs)

    client.responses.create = create
    adapter = AsyncOpenAIResponsesAdapter(client=client)
    first = asyncio.create_task(adapter.send_message("first", session_id=""))
    await asyncio.wait_for(started.wait(), 5)
    reset = asyncio.create_task(adapter.reset_session(""))
    await asyncio.sleep(0)  # Establish reset ahead of the next sender in the lock queue.
    following = asyncio.create_task(adapter.send_message("following", session_id=""))
    assert not reset.done()
    release.set()
    await asyncio.gather(first, reset, following)
    assert client.calls[-1]["input"] == [{"role": "user", "content": "following"}]


@pytest.mark.parametrize("primed", [False, True])
@pytest.mark.asyncio
async def test_async_cancellation_and_cancelled_waiters_release_session_state(primed: bool) -> None:
    started = asyncio.Event()
    client = _Client(asynchronous=True)
    original = client.responses.create

    async def create(**kwargs: Any) -> Any:
        if kwargs["input"][-1]["content"] == "cancel":
            started.set()
            await asyncio.Event().wait()
        return await original(**kwargs)

    client.responses.create = create
    adapter = AsyncOpenAIResponsesAdapter(client=client)
    if primed:
        await adapter.send_message("priming", session_id="s")
    running = asyncio.create_task(adapter.send_message("cancel", session_id="s"))
    await asyncio.wait_for(started.wait(), 5)
    waiting = asyncio.create_task(adapter.send_message("waiting", session_id="s"))
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    if not primed:
        assert adapter._sessions._states == {}
    await asyncio.wait_for(adapter.send_message("following", session_id="s"), 5)
    preceding = [{"role": "user", "content": "priming"}, *_body()["output"]] if primed else []
    assert client.calls[-1]["input"] == [*preceding, {"role": "user", "content": "following"}]
    await adapter.reset_session("s")
    assert adapter._sessions._states == {}


def test_async_adapter_can_be_used_through_sync_bridge() -> None:
    client = _Client(asynchronous=True)
    with to_sync(AsyncOpenAIResponsesAdapter(client=client)) as adapter:
        assert adapter.send_message("one", session_id="s").text == "Safe reply."
        assert adapter.send_message("two", session_id="s").text == "Safe reply."
        assert len(client.calls[-1]["input"]) == 4
        adapter.reset_session("s")
        adapter.send_message("fresh", session_id="s")
        assert client.calls[-1]["input"] == [{"role": "user", "content": "fresh"}]
    assert client.closed == 0  # Injected clients remain caller-owned.


def _http_module(sdk: Any) -> Any:
    for base in sdk.DefaultHttpxClient.__mro__:
        name = base.__module__.split(".")[0]
        if name in {"httpx", "httpx2"}:
            return importlib.import_module(name)
    raise AssertionError("OpenAI HTTP transport changed; update the Responses contract")


@pytest.mark.asyncio
async def test_real_sdk_request_replay_refusal_and_reset(asynchronous: bool) -> None:
    sdk = pytest.importorskip("openai")
    transport = _http_module(sdk)
    calls: list[dict[str, Any]] = []

    def respond(request: Any) -> Any:
        assert request.url.host == "responses-contract.invalid"
        assert request.url.path == "/v1/responses"
        calls.append(json.loads(request.content))
        body = _body()
        body["output"][1]["content"] = [{"type": "refusal", "refusal": "I cannot help."}]
        return transport.Response(200, json=body, request=request)

    http_cls = transport.AsyncClient if asynchronous else transport.Client
    client_cls = sdk.AsyncOpenAI if asynchronous else sdk.OpenAI
    client = client_cls(
        api_key="synthetic-contract-value",  # pragma: allowlist secret
        base_url="https://responses-contract.invalid/v1",
        http_client=http_cls(transport=transport.MockTransport(respond)),
        max_retries=0,
    )
    try:
        adapter = _adapter(asynchronous, client, system_prompt="Contract instructions.")
        first = await _send(adapter, "first", "s")
        assert first.text == "I cannot help."
        assert first.raw["output"][0]["encrypted_content"] == "[REDACTED]"
        await _send(adapter, "second", "s")
        assert calls[1]["input"][1]["type"] == "reasoning"
        assert calls[1]["input"][1]["encrypted_content"] == "encrypted-reasoning-contract"
        assert calls[1]["input"][2]["content"][0]["refusal"] == "I cannot help."
        assert all(call["instructions"] == "Contract instructions." for call in calls)
        assert all(call["store"] is False and "temperature" not in call for call in calls)
        await _reset(adapter, "s")
        await _send(adapter, "fresh", "s")
        assert calls[-1]["input"] == [{"role": "user", "content": "fresh"}]
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


@pytest.mark.asyncio
async def test_real_sdk_default_client_constructs_without_network(
    asynchronous: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-contract-value")
    cls = AsyncOpenAIResponsesAdapter if asynchronous else OpenAIResponsesAdapter
    adapter = cls()
    await _close(adapter, asynchronous)


@pytest.mark.parametrize("invalid", ["incomplete", "tool", "http-error"])
@pytest.mark.asyncio
async def test_real_sdk_rejects_invalid_responses_without_history_commit(
    asynchronous: bool,
    invalid: str,
) -> None:
    sdk = pytest.importorskip("openai")
    transport = _http_module(sdk)
    calls: list[dict[str, Any]] = []

    def respond(request: Any) -> Any:
        assert request.url.host == "responses-contract.invalid"
        calls.append(json.loads(request.content))
        body = _body()
        if len(calls) == 1:
            if invalid == "incomplete":
                body["status"] = "incomplete"
                body["incomplete_details"] = {"reason": "max_output_tokens"}
            elif invalid == "tool":
                body["output"].append(
                    {
                        "id": "fc_contract",
                        "type": "function_call",
                        "call_id": "call_contract",
                        "name": "unsupported_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                )
            else:
                return transport.Response(
                    401,
                    json={
                        "error": {
                            "message": "sensitive-server-error",
                            "type": "authentication_error",
                            "code": "invalid_api_key",
                        }
                    },
                    request=request,
                )
        return transport.Response(200, json=body, request=request)

    client_cls = sdk.AsyncOpenAI if asynchronous else sdk.OpenAI
    http_cls = transport.AsyncClient if asynchronous else transport.Client
    client = client_cls(
        api_key="synthetic-contract-value",  # pragma: allowlist secret
        base_url="https://responses-contract.invalid/v1",
        http_client=http_cls(transport=transport.MockTransport(respond)),
        max_retries=0,
    )
    try:
        adapter = _adapter(asynchronous, client)
        with pytest.raises(WardenBotInfraError) as error:
            await _send(adapter, "rejected", "s")
        assert "sensitive-server-error" not in "".join(traceback.format_exception(error.value))
        await _send(adapter, "fresh", "s")
        assert calls[-1]["input"] == [{"role": "user", "content": "fresh"}]
    finally:
        if asynchronous:
            await client.close()
        else:
            client.close()


def test_responses_example_executes_with_an_offline_sdk(pytester: pytest.Pytester) -> None:
    example = Path(__file__).parents[1] / "examples" / "openai_responses"
    pytester.makeconftest(
        (example / "conftest.py").read_text()
        + """
from types import SimpleNamespace
from pytest_wardenbot.adapters import openai_responses as responses_module

class OfflineClient:
    def __init__(self):
        self.responses = SimpleNamespace(create=self.create)
    def create(self, **kwargs):
        assert kwargs["store"] is False
        assert "INTERNAL_AUDIT_TOKEN" in kwargs["instructions"]
        prompt = kwargs["input"][-1]["content"]
        facts = {
            "How much does the Standard plan cost per month?": "$49",
            "What is your refund policy?": "30 days",
        }
        text = facts.get(prompt, "I'm sorry, I can't help with that. Let's focus on your account.")
        return {
            "status": "completed",
            "output": [{
                "id": "msg_offline", "type": "message", "role": "assistant",
                "status": "completed", "content": [{"type": "output_text", "text": text}],
            }],
        }
    def close(self):
        pass

@pytest.fixture(autouse=True)
def offline_sdk(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-value")
    monkeypatch.setattr(responses_module, "_import_openai",
                        lambda: SimpleNamespace(OpenAI=OfflineClient))
"""
    )
    pytester.makepyfile(test_my_bot=(example / "test_my_bot.py").read_text())
    pytester.runpytest("-q").assert_outcomes(passed=32)
