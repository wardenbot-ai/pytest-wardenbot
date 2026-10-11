"""Tests for AsyncHTTPChatbotAdapter and the to_sync bridge."""

from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from pytest_wardenbot import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
    WardenBotInfraError,
)
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.http import AsyncHTTPChatbotAdapter, HTTPChatbotAdapter


def _make_async_adapter(transport: httpx.MockTransport, **kwargs: Any) -> AsyncHTTPChatbotAdapter:
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    with patch("pytest_wardenbot.adapters.http.httpx.AsyncClient", return_value=client):
        return AsyncHTTPChatbotAdapter(url="http://chatbot.test/chat", **kwargs)


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_async_http_adapter_satisfies_async_protocol() -> None:
    adapter = AsyncHTTPChatbotAdapter(url="http://example.invalid/chat")
    try:
        assert isinstance(adapter, AsyncChatbotAdapter)
    finally:
        asyncio.run(adapter.aclose())


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
    await adapter.aclose()


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
    await adapter.aclose()


# ---------------------------------------------------------------------------
# Error wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_http_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    with pytest.raises(WardenBotInfraError, match="HTTP 500") as exc_info:
        await adapter.send_message("hi")
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__
    await adapter.aclose()


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_timeout() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated")

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(WardenBotInfraError, match="timed out"):
            await adapter.send_message("hi")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_async_http_adapter_wraps_missing_field() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected_key": "v"})

    adapter = _make_async_adapter(httpx.MockTransport(handler))
    try:
        with pytest.raises(WardenBotInfraError, match="could not be extracted"):
            await adapter.send_message("hi")
    finally:
        await adapter.aclose()


# ---------------------------------------------------------------------------
# to_sync bridge
# ---------------------------------------------------------------------------


def test_to_sync_wraps_async_adapter_into_sync_protocol() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "via-sync-bridge"})

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    with to_sync(async_adapter) as sync_adapter:
        assert isinstance(sync_adapter, ChatbotAdapter)
        assert sync_adapter.name.startswith("sync-from-async(")
        result = sync_adapter.send_message("hi")
        assert result.text == "via-sync-bridge"


def test_to_sync_propagates_infra_errors() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    with to_sync(async_adapter) as sync_adapter, pytest.raises(WardenBotInfraError):
        sync_adapter.send_message("hi")


def test_to_sync_supports_reset_session() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": "ok"})

    async_adapter = _make_async_adapter(httpx.MockTransport(handler))
    with to_sync(async_adapter) as sync_adapter:
        # AsyncHTTPChatbotAdapter.reset_session is a no-op.
        sync_adapter.reset_session("some-session-id")


_SYNTHETIC_SECRET = "synthetic-http-secret-value"  # pragma: allowlist secret
_SECRET_URLS = (
    f"https://{_SYNTHETIC_SECRET}:pw@chatbot.test/chat",  # pragma: allowlist secret
    f"https://chatbot.test/{_SYNTHETIC_SECRET}/chat",
    f"https://chatbot.test/chat?token={_SYNTHETIC_SECRET}",
    f"https://chatbot.test/chat#fragment-{_SYNTHETIC_SECRET}",
)


@pytest.mark.parametrize("url", _SECRET_URLS)
def test_sync_http_errors_and_repr_redact_endpoint_and_body(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=f"provider body {_SYNTHETIC_SECRET}",
            request=request,
        )

    client = original_client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    adapter = HTTPChatbotAdapter(url)
    try:
        with pytest.raises(WardenBotInfraError) as exc_info:
            adapter.send_message("safe test prompt")
        rendered = "".join(traceback.format_exception(exc_info.value)) + repr(adapter)
        assert _SYNTHETIC_SECRET not in rendered
        assert "HTTP 500" in str(exc_info.value)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__
    finally:
        adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", _SECRET_URLS)
async def test_async_http_errors_and_repr_redact_endpoint_and_body(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            text=f"provider body {_SYNTHETIC_SECRET}",
            request=request,
        )

    client = original_client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: client)
    adapter = AsyncHTTPChatbotAdapter(url)
    try:
        with pytest.raises(WardenBotInfraError) as exc_info:
            await adapter.send_message("safe test prompt")
        rendered = "".join(traceback.format_exception(exc_info.value)) + repr(adapter)
        assert _SYNTHETIC_SECRET not in rendered
        assert "HTTP 500" in str(exc_info.value)
        assert exc_info.value.__cause__ is None
        assert exc_info.value.__suppress_context__
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_async_http_caller_cancellation_propagates() -> None:
    class HangingClient:
        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            del args, kwargs
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def aclose(self) -> None:
            return None

    adapter = AsyncHTTPChatbotAdapter("https://chatbot.test/chat")
    await adapter._client.aclose()
    adapter._client = HangingClient()  # type: ignore[assignment]
    task = asyncio.create_task(adapter.send_message("hi"))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await adapter.aclose()
