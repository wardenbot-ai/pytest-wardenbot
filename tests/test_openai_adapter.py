"""Tests for OpenAIChatAdapter and AsyncOpenAIChatAdapter."""

from __future__ import annotations

import asyncio
import traceback
from types import SimpleNamespace

import pytest

from pytest_wardenbot import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
    WardenBotInfraError,
)
from pytest_wardenbot.adapters.openai_chat import (
    AsyncOpenAIChatAdapter,
    OpenAIChatAdapter,
)
from tests.fixtures.stub_vendor_clients import (
    StubAsyncOpenAIClient,
    StubOpenAIClient,
)

# ---------------------------------------------------------------------------
# Sync OpenAIChatAdapter
# ---------------------------------------------------------------------------


def test_openai_adapter_satisfies_chatbot_adapter_protocol() -> None:
    adapter = OpenAIChatAdapter(client=StubOpenAIClient())
    assert isinstance(adapter, ChatbotAdapter)


def test_openai_adapter_sends_user_message_and_extracts_text() -> None:
    client = StubOpenAIClient(response_text="hello there")
    adapter = OpenAIChatAdapter(client=client, system_prompt="You are helpful")
    result = adapter.send_message("hi")

    assert isinstance(result, ChatbotResponse)
    assert result.text == "hello there"
    assert result.latency_ms is not None and result.latency_ms >= 0
    call = client.completions_stub.calls[0]
    assert call["messages"] == [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "hi"},
    ]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0.0


def test_openai_adapter_omits_system_when_unset() -> None:
    client = StubOpenAIClient(response_text="ok")
    adapter = OpenAIChatAdapter(client=client)
    adapter.send_message("hi")

    messages = client.completions_stub.calls[0]["messages"]
    assert all(m["role"] != "system" for m in messages)


def test_openai_adapter_accepts_extra_request_fields() -> None:
    client = StubOpenAIClient(response_text="ok")
    adapter = OpenAIChatAdapter(
        client=client,
        extra_request_fields={"top_p": 0.9, "seed": 42},
    )
    adapter.send_message("hi")

    call = client.completions_stub.calls[0]
    assert call["top_p"] == 0.9
    assert call["seed"] == 42


def test_openai_adapter_wraps_vendor_exceptions_in_infra_error() -> None:
    boom = RuntimeError("synthetic-secret vendor payload")
    client = StubOpenAIClient(raise_exc=boom)
    adapter = OpenAIChatAdapter(client=client)
    with pytest.raises(
        WardenBotInfraError, match=r"OpenAI API call failed \(RuntimeError\)"
    ) as exc_info:
        adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "synthetic-secret" not in repr(exc_info.value)
    assert "synthetic-secret" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.parametrize("session_id", ["s", ""])
def test_openai_adapter_session_accumulates_turns(session_id: str) -> None:
    client = StubOpenAIClient(response_text="reply-1")
    adapter = OpenAIChatAdapter(client=client, system_prompt="You are helpful")

    adapter.send_message("turn-1", session_id=session_id)
    client.completions_stub.response_text = "reply-2"
    adapter.send_message("turn-2", session_id=session_id)

    second_call_messages = client.completions_stub.calls[1]["messages"]
    assert second_call_messages == [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "turn-1"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "turn-2"},
    ]


def test_openai_adapter_session_isolated_per_session_id() -> None:
    client = StubOpenAIClient(response_text="ok")
    adapter = OpenAIChatAdapter(client=client)

    adapter.send_message("for s1", session_id="s1")
    adapter.send_message("for s2", session_id="s2")

    # s2's call should not include s1's prior turn.
    s2_messages = client.completions_stub.calls[1]["messages"]
    assert s2_messages == [{"role": "user", "content": "for s2"}]


@pytest.mark.parametrize("session_id", ["s", ""])
def test_openai_adapter_reset_session_drops_history(session_id: str) -> None:
    client = StubOpenAIClient(response_text="ok")
    adapter = OpenAIChatAdapter(client=client)

    adapter.send_message("first", session_id=session_id)
    adapter.reset_session(session_id)
    adapter.send_message("second", session_id=session_id)

    second_messages = client.completions_stub.calls[1]["messages"]
    assert second_messages == [{"role": "user", "content": "second"}]


def test_openai_adapter_redacts_sensitive_response_fields_by_default() -> None:
    # Patch the stub to include a sensitive field in the model_dump output.
    from tests.fixtures.stub_vendor_clients import _StubCompletion

    client = StubOpenAIClient()

    def _create(**kwargs: object) -> _StubCompletion:
        del kwargs
        return _StubCompletion(
            text="ok",
            extra_raw={"authorization": "Bearer secret"},
        )

    client.completions_stub.create = _create  # type: ignore[method-assign]

    adapter = OpenAIChatAdapter(client=client)
    result = adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["authorization"] == "[REDACTED]"


def test_openai_adapter_keeps_raw_when_opted_in() -> None:
    from tests.fixtures.stub_vendor_clients import _StubCompletion

    client = StubOpenAIClient()

    def _create(**kwargs: object) -> _StubCompletion:
        del kwargs
        return _StubCompletion(text="ok", extra_raw={"api_key": "sk-keep"})

    client.completions_stub.create = _create  # type: ignore[method-assign]

    adapter = OpenAIChatAdapter(client=client, keep_sensitive_response_fields=True)
    result = adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["api_key"] == "sk-keep"


def test_openai_adapter_does_not_store_object_repr_as_raw_payload() -> None:
    class Response:
        def __init__(self) -> None:
            self.choices = [SimpleNamespace(message=SimpleNamespace(content="ok"))]

        def __repr__(self) -> str:
            return "Response(synthetic-secret)"

    class Completions:
        def create(self, **kwargs: object) -> Response:
            del kwargs
            return Response()

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    response = OpenAIChatAdapter(client=client).send_message("hi")
    assert response.raw == {"unavailable": "Response object does not support model_dump()."}
    assert "synthetic-secret" not in repr(response.raw)


@pytest.mark.parametrize(
    "content",
    [
        {"secret": "malformed-secret"},  # pragma: allowlist secret
        ["malformed-secret"],
        12,
    ],
)
def test_openai_adapter_rejects_non_text_content_without_leaking(content: object) -> None:
    class Completions:
        def create(self, **kwargs: object) -> object:
            del kwargs
            message = SimpleNamespace(content=content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    adapter = OpenAIChatAdapter(client=client)
    with pytest.raises(WardenBotInfraError, match="content is not text") as exc_info:
        adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "malformed-secret" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


def test_openai_adapter_preserves_empty_response_and_hides_model_dump_failure() -> None:
    class Response:
        def __init__(self) -> None:
            self.choices = [SimpleNamespace(message=SimpleNamespace(content=None))]

        def model_dump(self) -> dict[str, object]:
            raise RuntimeError("dump-secret")

    class Completions:
        def create(self, **kwargs: object) -> Response:
            del kwargs
            return Response()

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    result = OpenAIChatAdapter(client=client).send_message("hi")
    assert result.text == ""
    assert result.raw == {"unavailable": "Response payload could not be serialized."}
    assert "dump-secret" not in repr(result)


def test_openai_adapter_install_hint_on_missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    """If no client provided AND openai isn't importable, raise install hint."""
    import sys

    # Hide any installed openai for this test.
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match=r"pytest-wardenbot\[openai\]"):
        OpenAIChatAdapter()


def test_sync_openai_client_close_respects_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest_wardenbot.adapters.openai_chat as module

    class ClosableClient(StubOpenAIClient):
        closed = 0

        def close(self) -> None:
            self.closed += 1

    owned = ClosableClient()
    monkeypatch.setattr(module, "_import_openai", lambda: SimpleNamespace(OpenAI=lambda: owned))
    OpenAIChatAdapter().close()
    assert owned.closed == 1

    injected = ClosableClient()
    OpenAIChatAdapter(client=injected).close()
    assert injected.closed == 0


# ---------------------------------------------------------------------------
# Async AsyncOpenAIChatAdapter
# ---------------------------------------------------------------------------


def test_async_openai_adapter_satisfies_async_protocol() -> None:
    adapter = AsyncOpenAIChatAdapter(client=StubAsyncOpenAIClient())
    assert isinstance(adapter, AsyncChatbotAdapter)


@pytest.mark.asyncio
async def test_async_openai_adapter_sends_and_extracts() -> None:
    client = StubAsyncOpenAIClient(response_text="async-hi")
    adapter = AsyncOpenAIChatAdapter(client=client, system_prompt="sys")
    result = await adapter.send_message("hi")

    assert result.text == "async-hi"
    assert client.completions_stub.calls[0]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
    ]


@pytest.mark.asyncio
async def test_async_openai_adapter_wraps_exceptions() -> None:
    boom = RuntimeError("synthetic-secret vendor payload")
    client = StubAsyncOpenAIClient(raise_exc=boom)
    adapter = AsyncOpenAIChatAdapter(client=client)
    with pytest.raises(
        WardenBotInfraError, match=r"OpenAI API call failed \(RuntimeError\)"
    ) as exc_info:
        await adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "synthetic-secret" not in repr(exc_info.value)
    assert "synthetic-secret" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.asyncio
async def test_async_openai_client_close_respects_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytest_wardenbot.adapters.openai_chat as module

    class ClosableClient(StubAsyncOpenAIClient):
        closed = 0

        async def close(self) -> None:
            self.closed += 1

    owned = ClosableClient()
    monkeypatch.setattr(
        module, "_import_openai", lambda: SimpleNamespace(AsyncOpenAI=lambda: owned)
    )
    await AsyncOpenAIChatAdapter().aclose()
    assert owned.closed == 1

    injected = ClosableClient()
    await AsyncOpenAIChatAdapter(client=injected).aclose()
    assert injected.closed == 0


@pytest.mark.asyncio
async def test_async_openai_caller_cancellation_propagates() -> None:
    class HangingCompletions:
        async def create(self, **kwargs: object) -> object:
            del kwargs
            await asyncio.Event().wait()
            return object()

    client = SimpleNamespace(chat=SimpleNamespace(completions=HangingCompletions()))
    task = asyncio.create_task(AsyncOpenAIChatAdapter(client=client).send_message("hi"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["s", ""])
async def test_async_openai_adapter_session_memory(session_id: str) -> None:
    client = StubAsyncOpenAIClient(response_text="r1")
    adapter = AsyncOpenAIChatAdapter(client=client)
    await adapter.send_message("t1", session_id=session_id)
    client.completions_stub.response_text = "r2"
    await adapter.send_message("t2", session_id=session_id)

    second = client.completions_stub.calls[1]["messages"]
    assert second == [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "t2"},
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["s", ""])
async def test_async_openai_adapter_reset_session(session_id: str) -> None:
    client = StubAsyncOpenAIClient(response_text="ok")
    adapter = AsyncOpenAIChatAdapter(client=client)
    await adapter.send_message("first", session_id=session_id)
    await adapter.reset_session(session_id)
    await adapter.send_message("second", session_id=session_id)

    assert client.completions_stub.calls[1]["messages"] == [{"role": "user", "content": "second"}]
