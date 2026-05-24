"""Tests for AsyncHTTPChatbotAdapter and the to_sync bridge."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from pytest_wardenbot import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
    WardenBotInfraError,
)
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.http import AsyncHTTPChatbotAdapter


def _make_async_adapter(transport: httpx.MockTransport, **kwargs: Any) -> AsyncHTTPChatbotAdapter:
    adapter = AsyncHTTPChatbotAdapter(url="http://chatbot.test/chat", **kwargs)
    # Swap the auto-created AsyncClient for one wired to the MockTransport.

    # Closing the AsyncClient from sync code is fine when no requests are in
    # flight — and the AsyncClient is brand new at this point.
    adapter._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return adapter


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_async_http_adapter_satisfies_async_protocol() -> None:
    adapter = AsyncHTTPChatbotAdapter(url="http://example.invalid/chat")
    assert isinstance(adapter, AsyncChatbotAdapter)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_http_adapter_posts_and_extracts() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"response": "async-hello"})

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    result = await adapter.send_message("hi")

    assert isinstance(result, ChatbotResponse)
    assert result.text == "async-hello"
    assert captured["body"] == {"message": "hi"}


@pytest.mark.asyncio
async def test_async_http_adapter_redacts_sensitive_response_fields_by_default() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": "ok", "Authorization": "Bearer secret"},
        )

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    result = await adapter.send_message("hi")
    assert result.raw is not None
    assert result.raw["Authorization"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_http_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    with pytest.raises(WardenBotInfraError, match="HTTP 500"):
        await adapter.send_message("hi")


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_timeout() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated")

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    with pytest.raises(WardenBotInfraError, match="timed out"):
        await adapter.send_message("hi")


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_missing_field() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_key": "v"})

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    with pytest.raises(WardenBotInfraError, match=r"response.*not found"):
        await adapter.send_message("hi")


# ---------------------------------------------------------------------------
# to_sync bridge
# ---------------------------------------------------------------------------


def test_to_sync_wraps_async_adapter_into_sync_protocol() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "via-sync-bridge"})

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    sync_adapter = to_sync(async_adapter)

    assert isinstance(sync_adapter, ChatbotAdapter)
    assert sync_adapter.name.startswith("sync-from-async(")
    result = sync_adapter.send_message("hi")
    assert result.text == "via-sync-bridge"


def test_to_sync_propagates_infra_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    sync_adapter = to_sync(async_adapter)
    with pytest.raises(WardenBotInfraError):
        sync_adapter.send_message("hi")


def test_to_sync_supports_reset_session() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "ok"})

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    sync_adapter = to_sync(async_adapter)
    # Just verify no exception; the AsyncHTTPChatbotAdapter.reset_session is no-op.
    sync_adapter.reset_session("some-session-id")
