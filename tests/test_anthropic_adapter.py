"""Tests for AnthropicMessagesAdapter and AsyncAnthropicMessagesAdapter."""

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
from pytest_wardenbot.adapters.anthropic_msgs import (
    AnthropicMessagesAdapter,
    AsyncAnthropicMessagesAdapter,
)
from tests.fixtures.stub_vendor_clients import (
    StubAnthropicClient,
    StubAsyncAnthropicClient,
)

# ---------------------------------------------------------------------------
# Sync AnthropicMessagesAdapter
# ---------------------------------------------------------------------------


def test_anthropic_adapter_satisfies_chatbot_adapter_protocol() -> None:
    adapter = AnthropicMessagesAdapter(client=StubAnthropicClient())
    assert isinstance(adapter, ChatbotAdapter)


def test_anthropic_adapter_sends_messages_with_system_top_level() -> None:
    client = StubAnthropicClient(response_text="hi back")
    adapter = AnthropicMessagesAdapter(client=client, system_prompt="You are helpful")
    result = adapter.send_message("hi")

    assert isinstance(result, ChatbotResponse)
    assert result.text == "hi back"
    call = client.messages.calls[0]
    # Anthropic's system arrives as a top-level kwarg, NOT in messages.
    assert call["system"] == "You are helpful"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert call["model"] == "claude-haiku-4-5"
    assert call["max_tokens"] == 1024
    assert "temperature" not in call


def test_anthropic_adapter_sends_explicit_temperature_in_extra_body() -> None:
    client = StubAnthropicClient(response_text="hi back")
    adapter = AnthropicMessagesAdapter(
        client=client,
        temperature=0.2,
        extra_request_fields={"extra_body": {"custom": "value"}},
    )
    adapter.send_message("hi")

    assert client.messages.calls[0]["extra_body"] == {
        "custom": "value",
        "temperature": 0.2,
    }


def test_anthropic_adapter_omits_system_kwarg_when_unset() -> None:
    client = StubAnthropicClient(response_text="ok")
    adapter = AnthropicMessagesAdapter(client=client)
    adapter.send_message("hi")

    call = client.messages.calls[0]
    assert "system" not in call


def test_anthropic_adapter_wraps_vendor_exceptions_in_infra_error() -> None:
    boom = RuntimeError("synthetic-secret vendor payload")
    client = StubAnthropicClient(raise_exc=boom)
    adapter = AnthropicMessagesAdapter(client=client)
    with pytest.raises(
        WardenBotInfraError, match=r"Anthropic API call failed \(RuntimeError\)"
    ) as exc_info:
        adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "synthetic-secret" not in repr(exc_info.value)
    assert "synthetic-secret" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.parametrize("session_id", ["s", ""])
def test_anthropic_adapter_session_accumulates_turns(session_id: str) -> None:
    client = StubAnthropicClient(response_text="reply-1")
    adapter = AnthropicMessagesAdapter(client=client)

    adapter.send_message("turn-1", session_id=session_id)
    client.messages.response_text = "reply-2"
    adapter.send_message("turn-2", session_id=session_id)

    second = client.messages.calls[1]["messages"]
    assert second == [
        {"role": "user", "content": "turn-1"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "turn-2"},
    ]


@pytest.mark.parametrize("session_id", ["s", ""])
def test_anthropic_adapter_reset_session_drops_history(session_id: str) -> None:
    client = StubAnthropicClient(response_text="ok")
    adapter = AnthropicMessagesAdapter(client=client)
    adapter.send_message("first", session_id=session_id)
    adapter.reset_session(session_id)
    adapter.send_message("second", session_id=session_id)

    assert client.messages.calls[1]["messages"] == [{"role": "user", "content": "second"}]


def test_anthropic_adapter_redacts_raw_by_default() -> None:
    from tests.fixtures.stub_vendor_clients import _StubAnthropicMessage

    client = StubAnthropicClient()

    def _create(**kwargs: object) -> _StubAnthropicMessage:
        del kwargs
        return _StubAnthropicMessage(text="ok", extra_raw={"x-api-key": "leaked"})

    client.messages.create = _create  # type: ignore[method-assign]

    adapter = AnthropicMessagesAdapter(client=client)
    result = adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["x-api-key"] == "[REDACTED]"


def test_anthropic_adapter_does_not_store_object_repr_as_raw_payload() -> None:
    class Message:
        def __init__(self) -> None:
            self.content = [SimpleNamespace(type="text", text="ok")]

        def __repr__(self) -> str:
            return "Message(synthetic-secret)"

    class Messages:
        def create(self, **kwargs: object) -> Message:
            del kwargs
            return Message()

    client = SimpleNamespace(messages=Messages())
    response = AnthropicMessagesAdapter(client=client).send_message("hi")
    assert response.raw == {"unavailable": "Response object does not support model_dump()."}
    assert "synthetic-secret" not in repr(response.raw)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "malformed-secret",
        object(),
        [
            SimpleNamespace(
                type="text",
                text={"secret": "malformed-secret"},  # pragma: allowlist secret
            )
        ],
    ],
)
def test_anthropic_adapter_rejects_malformed_text_without_leaking(content: object) -> None:
    class Messages:
        def create(self, **kwargs: object) -> object:
            del kwargs
            return SimpleNamespace(content=content)

    adapter = AnthropicMessagesAdapter(client=SimpleNamespace(messages=Messages()))
    with pytest.raises(WardenBotInfraError) as exc_info:
        adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "malformed-secret" not in rendered
    assert "object at" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


def test_anthropic_adapter_preserves_empty_text_and_hides_model_dump_failure() -> None:
    class Message:
        def __init__(self) -> None:
            self.content = [SimpleNamespace(type="text", text="")]

        def model_dump(self) -> dict[str, object]:
            raise RuntimeError("dump-secret")

    class Messages:
        def create(self, **kwargs: object) -> Message:
            del kwargs
            return Message()

    client = SimpleNamespace(messages=Messages())
    result = AnthropicMessagesAdapter(client=client).send_message("hi")
    assert result.text == ""
    assert result.raw == {"unavailable": "Response payload could not be serialized."}
    assert "dump-secret" not in repr(result)


def test_anthropic_adapter_install_hint_on_missing_dep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match=r"pytest-wardenbot\[anthropic\]"):
        AnthropicMessagesAdapter()


def test_sync_anthropic_client_close_respects_ownership(monkeypatch: pytest.MonkeyPatch) -> None:
    import pytest_wardenbot.adapters.anthropic_msgs as module

    class ClosableClient(StubAnthropicClient):
        closed = 0

        def close(self) -> None:
            self.closed += 1

    owned = ClosableClient()
    monkeypatch.setattr(
        module, "_import_anthropic", lambda: SimpleNamespace(Anthropic=lambda: owned)
    )
    AnthropicMessagesAdapter().close()
    assert owned.closed == 1

    injected = ClosableClient()
    AnthropicMessagesAdapter(client=injected).close()
    assert injected.closed == 0


# ---------------------------------------------------------------------------
# Async AsyncAnthropicMessagesAdapter
# ---------------------------------------------------------------------------


def test_async_anthropic_adapter_satisfies_async_protocol() -> None:
    adapter = AsyncAnthropicMessagesAdapter(client=StubAsyncAnthropicClient())
    assert isinstance(adapter, AsyncChatbotAdapter)


@pytest.mark.asyncio
async def test_async_anthropic_adapter_sends_and_extracts() -> None:
    client = StubAsyncAnthropicClient(response_text="async-reply")
    adapter = AsyncAnthropicMessagesAdapter(client=client, system_prompt="sys")
    result = await adapter.send_message("hi")

    assert result.text == "async-reply"
    call = client.messages.calls[0]
    assert call["system"] == "sys"
    assert call["messages"] == [{"role": "user", "content": "hi"}]
    assert "temperature" not in call


@pytest.mark.asyncio
async def test_async_anthropic_adapter_sends_explicit_temperature_in_extra_body() -> None:
    client = StubAsyncAnthropicClient(response_text="async-reply")
    adapter = AsyncAnthropicMessagesAdapter(client=client, temperature=0.2)
    await adapter.send_message("hi")

    assert client.messages.calls[0]["extra_body"] == {"temperature": 0.2}


@pytest.mark.asyncio
async def test_async_anthropic_adapter_wraps_exceptions() -> None:
    boom = ValueError("synthetic-secret vendor payload")
    client = StubAsyncAnthropicClient(raise_exc=boom)
    adapter = AsyncAnthropicMessagesAdapter(client=client)
    with pytest.raises(
        WardenBotInfraError, match=r"Anthropic API call failed \(ValueError\)"
    ) as exc_info:
        await adapter.send_message("hi")
    rendered = "".join(traceback.format_exception(exc_info.value))
    assert "synthetic-secret" not in repr(exc_info.value)
    assert "synthetic-secret" not in rendered
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__


@pytest.mark.asyncio
async def test_async_anthropic_client_close_respects_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytest_wardenbot.adapters.anthropic_msgs as module

    class ClosableClient(StubAsyncAnthropicClient):
        closed = 0

        async def close(self) -> None:
            self.closed += 1

    owned = ClosableClient()
    monkeypatch.setattr(
        module,
        "_import_anthropic",
        lambda: SimpleNamespace(AsyncAnthropic=lambda: owned),
    )
    await AsyncAnthropicMessagesAdapter().aclose()
    assert owned.closed == 1

    injected = ClosableClient()
    await AsyncAnthropicMessagesAdapter(client=injected).aclose()
    assert injected.closed == 0


@pytest.mark.asyncio
async def test_async_anthropic_caller_cancellation_propagates() -> None:
    class HangingMessages:
        async def create(self, **kwargs: object) -> object:
            del kwargs
            await asyncio.Event().wait()
            return object()

    client = SimpleNamespace(messages=HangingMessages())
    task = asyncio.create_task(AsyncAnthropicMessagesAdapter(client=client).send_message("hi"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", ["s", ""])
async def test_async_anthropic_adapter_session_memory(session_id: str) -> None:
    client = StubAsyncAnthropicClient(response_text="r1")
    adapter = AsyncAnthropicMessagesAdapter(client=client)
    await adapter.send_message("t1", session_id=session_id)
    client.messages.response_text = "r2"
    await adapter.send_message("t2", session_id=session_id)

    assert client.messages.calls[1]["messages"] == [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "t2"},
    ]
