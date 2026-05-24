"""Tests for AnthropicMessagesAdapter and AsyncAnthropicMessagesAdapter."""

from __future__ import annotations

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
    assert call["temperature"] == 0.0


def test_anthropic_adapter_omits_system_kwarg_when_unset() -> None:
    client = StubAnthropicClient(response_text="ok")
    adapter = AnthropicMessagesAdapter(client=client)
    adapter.send_message("hi")

    call = client.messages.calls[0]
    assert "system" not in call


def test_anthropic_adapter_wraps_vendor_exceptions_in_infra_error() -> None:
    boom = RuntimeError("server overloaded")
    client = StubAnthropicClient(raise_exc=boom)
    adapter = AnthropicMessagesAdapter(client=client)
    with pytest.raises(WardenBotInfraError, match="server overloaded") as exc_info:
        adapter.send_message("hi")
    assert exc_info.value.__cause__ is boom


def test_anthropic_adapter_session_accumulates_turns() -> None:
    client = StubAnthropicClient(response_text="reply-1")
    adapter = AnthropicMessagesAdapter(client=client)

    adapter.send_message("turn-1", session_id="s1")
    client.messages.response_text = "reply-2"
    adapter.send_message("turn-2", session_id="s1")

    second = client.messages.calls[1]["messages"]
    assert second == [
        {"role": "user", "content": "turn-1"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "turn-2"},
    ]


def test_anthropic_adapter_reset_session_drops_history() -> None:
    client = StubAnthropicClient(response_text="ok")
    adapter = AnthropicMessagesAdapter(client=client)
    adapter.send_message("first", session_id="s")
    adapter.reset_session("s")
    adapter.send_message("second", session_id="s")

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


def test_anthropic_adapter_install_hint_on_missing_dep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match=r"pytest-wardenbot\[anthropic\]"):
        AnthropicMessagesAdapter()


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


@pytest.mark.asyncio
async def test_async_anthropic_adapter_wraps_exceptions() -> None:
    boom = ValueError("bad request")
    client = StubAsyncAnthropicClient(raise_exc=boom)
    adapter = AsyncAnthropicMessagesAdapter(client=client)
    with pytest.raises(WardenBotInfraError, match="bad request") as exc_info:
        await adapter.send_message("hi")
    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_async_anthropic_adapter_session_memory() -> None:
    client = StubAsyncAnthropicClient(response_text="r1")
    adapter = AsyncAnthropicMessagesAdapter(client=client)
    await adapter.send_message("t1", session_id="s")
    client.messages.response_text = "r2"
    await adapter.send_message("t2", session_id="s")

    assert client.messages.calls[1]["messages"] == [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "t2"},
    ]
