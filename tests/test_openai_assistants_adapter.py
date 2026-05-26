"""Tests for OpenAIAssistantsAdapter and AsyncOpenAIAssistantsAdapter."""

from __future__ import annotations

import warnings
from typing import Any

import pytest

from pytest_wardenbot import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
    WardenBotInfraError,
)
from pytest_wardenbot.adapters.openai_assistants import (
    AsyncOpenAIAssistantsAdapter,
    OpenAIAssistantsAdapter,
)
from tests.fixtures.stub_vendor_clients import (
    StubAsyncOpenAIAssistantsClient,
    StubOpenAIAssistantsClient,
)


def _sync(client: Any, **kwargs: Any) -> OpenAIAssistantsAdapter:
    """Construct the adapter, suppressing the (expected) DeprecationWarning."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return OpenAIAssistantsAdapter(assistant_id="asst_test", client=client, **kwargs)


def _async(client: Any, **kwargs: Any) -> AsyncOpenAIAssistantsAdapter:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return AsyncOpenAIAssistantsAdapter(assistant_id="asst_test", client=client, **kwargs)


# ---------------------------------------------------------------------------
# Sync OpenAIAssistantsAdapter
# ---------------------------------------------------------------------------


def test_assistants_adapter_satisfies_protocol() -> None:
    adapter = _sync(StubOpenAIAssistantsClient())
    assert isinstance(adapter, ChatbotAdapter)


def test_assistants_adapter_emits_deprecation_warning() -> None:
    with pytest.warns(DeprecationWarning, match="2026-08-26"):
        OpenAIAssistantsAdapter(assistant_id="asst_x", client=StubOpenAIAssistantsClient())


def test_assistants_adapter_sends_and_extracts_text() -> None:
    client = StubOpenAIAssistantsClient(response_text="hello there")
    adapter = _sync(client)
    result = adapter.send_message("hi")

    assert isinstance(result, ChatbotResponse)
    assert result.text == "hello there"
    assert result.latency_ms is not None and result.latency_ms >= 0

    msg_call = client.threads_stub.messages.create_calls[0]
    assert msg_call["role"] == "user"
    assert msg_call["content"] == "hi"
    run_call = client.threads_stub.runs.create_calls[0]
    assert run_call["assistant_id"] == "asst_test"


def test_assistants_adapter_empty_reply_returns_empty_text() -> None:
    # An empty assistant reply is valid output, not an infra error.
    adapter = _sync(StubOpenAIAssistantsClient(response_text=""))
    result = adapter.send_message("hi")
    assert result.text == ""


def test_assistants_adapter_polls_until_complete() -> None:
    client = StubOpenAIAssistantsClient(
        response_text="done", run_statuses=("in_progress", "completed")
    )
    adapter = _sync(client, poll_interval_s=0.001)
    result = adapter.send_message("hi")

    assert result.text == "done"
    # create() returned in_progress, so exactly one retrieve() was needed.
    assert len(client.threads_stub.runs.retrieve_calls) == 1


def test_assistants_adapter_session_reuses_one_thread() -> None:
    client = StubOpenAIAssistantsClient()
    adapter = _sync(client)
    adapter.send_message("t1", session_id="s1")
    adapter.send_message("t2", session_id="s1")

    # One thread created for the session, reused on the second call.
    assert client.threads_stub.created == 1
    assert client.threads_stub.deleted == []


def test_assistants_adapter_sessions_isolated() -> None:
    client = StubOpenAIAssistantsClient()
    adapter = _sync(client)
    adapter.send_message("for s1", session_id="s1")
    adapter.send_message("for s2", session_id="s2")

    assert client.threads_stub.created == 2


def test_assistants_adapter_reset_session_deletes_thread() -> None:
    client = StubOpenAIAssistantsClient()
    adapter = _sync(client)
    adapter.send_message("first", session_id="s1")
    adapter.reset_session("s1")

    assert client.threads_stub.deleted == ["thread_1"]
    # Next call starts a fresh thread.
    adapter.send_message("second", session_id="s1")
    assert client.threads_stub.created == 2


def test_assistants_adapter_stateless_creates_and_deletes_thread() -> None:
    client = StubOpenAIAssistantsClient()
    adapter = _sync(client)
    adapter.send_message("one-shot")  # no session_id

    assert client.threads_stub.created == 1
    assert client.threads_stub.deleted == ["thread_1"]


def test_assistants_adapter_run_failure_raises_infra_error() -> None:
    client = StubOpenAIAssistantsClient(run_statuses=("failed",), last_error="model exploded")
    adapter = _sync(client)
    with pytest.raises(WardenBotInfraError, match="failed"):
        adapter.send_message("hi")


def test_assistants_adapter_requires_action_raises() -> None:
    client = StubOpenAIAssistantsClient(run_statuses=("requires_action",))
    adapter = _sync(client)
    with pytest.raises(WardenBotInfraError, match="requires_action"):
        adapter.send_message("hi")


def test_assistants_adapter_timeout_raises() -> None:
    client = StubOpenAIAssistantsClient(run_statuses=("in_progress",))
    adapter = _sync(client, timeout_s=0.05, poll_interval_s=0.01)
    with pytest.raises(WardenBotInfraError, match="did not complete"):
        adapter.send_message("hi")


def test_assistants_adapter_wraps_vendor_exceptions() -> None:
    boom = RuntimeError("rate limit")
    client = StubOpenAIAssistantsClient(raise_exc=boom)
    adapter = _sync(client)
    with pytest.raises(WardenBotInfraError, match="rate limit") as exc_info:
        adapter.send_message("hi")
    assert exc_info.value.__cause__ is boom


def test_assistants_adapter_redacts_raw_by_default() -> None:
    raw = {"authorization": "Bearer secret"}  # pragma: allowlist secret
    client = StubOpenAIAssistantsClient(extra_raw=raw)
    adapter = _sync(client)
    result = adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["authorization"] == "[REDACTED]"


def test_assistants_adapter_keeps_raw_when_opted_in() -> None:
    raw = {"api_key": "sk-keep"}  # pragma: allowlist secret
    client = StubOpenAIAssistantsClient(extra_raw=raw)
    adapter = _sync(client, keep_sensitive_response_fields=True)
    result = adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["api_key"] == "sk-keep"  # pragma: allowlist secret


def test_assistants_adapter_install_hint_on_missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "openai", None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ImportError, match=r"pytest-wardenbot\[openai\]"):
            OpenAIAssistantsAdapter(assistant_id="asst_x")


# ---------------------------------------------------------------------------
# Async AsyncOpenAIAssistantsAdapter
# ---------------------------------------------------------------------------


def test_async_assistants_adapter_satisfies_protocol() -> None:
    adapter = _async(StubAsyncOpenAIAssistantsClient())
    assert isinstance(adapter, AsyncChatbotAdapter)


@pytest.mark.asyncio
async def test_async_assistants_sends_and_extracts() -> None:
    client = StubAsyncOpenAIAssistantsClient(response_text="async-hi")
    adapter = _async(client)
    result = await adapter.send_message("hi")
    assert result.text == "async-hi"
    assert client.threads_stub.runs.create_calls[0]["assistant_id"] == "asst_test"


@pytest.mark.asyncio
async def test_async_assistants_session_reuses_thread() -> None:
    client = StubAsyncOpenAIAssistantsClient()
    adapter = _async(client)
    await adapter.send_message("t1", session_id="s")
    await adapter.send_message("t2", session_id="s")
    assert client.threads_stub.created == 1


@pytest.mark.asyncio
async def test_async_assistants_reset_session_deletes_thread() -> None:
    client = StubAsyncOpenAIAssistantsClient()
    adapter = _async(client)
    await adapter.send_message("first", session_id="s")
    await adapter.reset_session("s")
    assert client.threads_stub.deleted == ["thread_1"]


@pytest.mark.asyncio
async def test_async_assistants_run_failure_raises() -> None:
    client = StubAsyncOpenAIAssistantsClient(run_statuses=("failed",), last_error="boom")
    adapter = _async(client)
    with pytest.raises(WardenBotInfraError, match="failed"):
        await adapter.send_message("hi")


@pytest.mark.asyncio
async def test_async_assistants_timeout_raises() -> None:
    client = StubAsyncOpenAIAssistantsClient(run_statuses=("in_progress",))
    adapter = _async(client, timeout_s=0.05, poll_interval_s=0.01)
    with pytest.raises(WardenBotInfraError, match="did not complete"):
        await adapter.send_message("hi")
