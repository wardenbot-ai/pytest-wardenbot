"""Tests for OpenAIChatAdapter and AsyncOpenAIChatAdapter."""

from __future__ import annotations

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
    boom = RuntimeError("rate limit")
    client = StubOpenAIClient(raise_exc=boom)
    adapter = OpenAIChatAdapter(client=client)
    with pytest.raises(WardenBotInfraError, match="rate limit") as exc_info:
        adapter.send_message("hi")
    assert exc_info.value.__cause__ is boom


def test_openai_adapter_session_accumulates_turns() -> None:
    client = StubOpenAIClient(response_text="reply-1")
    adapter = OpenAIChatAdapter(client=client, system_prompt="You are helpful")

    adapter.send_message("turn-1", session_id="s1")
    client.completions_stub.response_text = "reply-2"
    adapter.send_message("turn-2", session_id="s1")

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


def test_openai_adapter_reset_session_drops_history() -> None:
    client = StubOpenAIClient(response_text="ok")
    adapter = OpenAIChatAdapter(client=client)

    adapter.send_message("first", session_id="s1")
    adapter.reset_session("s1")
    adapter.send_message("second", session_id="s1")

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


def test_openai_adapter_install_hint_on_missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    """If no client provided AND openai isn't importable, raise install hint."""
    import sys

    # Hide any installed openai for this test.
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match=r"pytest-wardenbot\[openai\]"):
        OpenAIChatAdapter()


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
    boom = RuntimeError("network")
    client = StubAsyncOpenAIClient(raise_exc=boom)
    adapter = AsyncOpenAIChatAdapter(client=client)
    with pytest.raises(WardenBotInfraError, match="network") as exc_info:
        await adapter.send_message("hi")
    assert exc_info.value.__cause__ is boom


@pytest.mark.asyncio
async def test_async_openai_adapter_session_memory() -> None:
    client = StubAsyncOpenAIClient(response_text="r1")
    adapter = AsyncOpenAIChatAdapter(client=client)
    await adapter.send_message("t1", session_id="s")
    client.completions_stub.response_text = "r2"
    await adapter.send_message("t2", session_id="s")

    second = client.completions_stub.calls[1]["messages"]
    assert second == [
        {"role": "user", "content": "t1"},
        {"role": "assistant", "content": "r1"},
        {"role": "user", "content": "t2"},
    ]


@pytest.mark.asyncio
async def test_async_openai_adapter_reset_session() -> None:
    client = StubAsyncOpenAIClient(response_text="ok")
    adapter = AsyncOpenAIChatAdapter(client=client)
    await adapter.send_message("first", session_id="s")
    await adapter.reset_session("s")
    await adapter.send_message("second", session_id="s")

    assert client.completions_stub.calls[1]["messages"] == [{"role": "user", "content": "second"}]
