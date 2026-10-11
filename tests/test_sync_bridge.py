"""Persistent-loop bridge contracts, including a real SDK keep-alive transport."""

from __future__ import annotations

import asyncio
import gc
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from unittest.mock import Mock

import pytest

from pytest_wardenbot import ChatbotAdapter, ChatbotResponse, WardenBotInfraError
from pytest_wardenbot.adapters import to_sync
from pytest_wardenbot.adapters.openai_responses import AsyncOpenAIResponsesAdapter


class _Adapter:
    name = "recording-async"
    stateful = True

    def __init__(self) -> None:
        self.loops: list[asyncio.AbstractEventLoop] = []
        self.history: dict[str, list[str]] = {}
        self.closed = 0
        self.close_error = False

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        self.loops.append(asyncio.get_running_loop())
        if prompt == "fail":
            raise WardenBotInfraError("Expected failure")
        if prompt == "cancel":
            raise asyncio.CancelledError
        if session_id is not None:
            self.history.setdefault(session_id, []).append(prompt)
        return ChatbotResponse(text=prompt)

    async def reset_session(self, session_id: str) -> None:
        self.loops.append(asyncio.get_running_loop())
        self.history.pop(session_id, None)

    async def aclose(self) -> None:
        self.loops.append(asyncio.get_running_loop())
        self.closed += 1
        if self.close_error:
            raise ValueError("Expected close failure")


def test_repeated_sends_reset_and_close_share_one_loop() -> None:
    inner = _Adapter()
    with to_sync(inner) as adapter:
        assert isinstance(adapter, ChatbotAdapter)
        assert adapter.stateful is True
        assert adapter.send_message("first", session_id="s").text == "first"
        adapter.send_message("second", session_id="s")
        assert inner.history == {"s": ["first", "second"]}
        adapter.reset_session("s")
        adapter.send_message("fresh", session_id="s")
        assert inner.history == {"s": ["fresh"]}
    assert inner.closed == 1
    assert all(loop is inner.loops[0] for loop in inner.loops)
    assert inner.loops[0].is_closed()
    adapter.close()
    assert inner.closed == 1


def test_send_errors_and_cancellation_do_not_close_or_poison_bridge() -> None:
    inner = _Adapter()
    with to_sync(inner) as adapter:
        with pytest.raises(WardenBotInfraError, match="Expected failure"):
            adapter.send_message("fail", session_id="s")
        with pytest.raises(asyncio.CancelledError):
            adapter.send_message("cancel", session_id="s")
        assert adapter.send_message("next", session_id="s").text == "next"
    assert inner.history == {"s": ["next"]}
    assert len(set(inner.loops)) == 1


def test_context_exit_after_body_error_still_closes_adapter_and_loop() -> None:
    inner = _Adapter()
    with pytest.raises(ValueError, match="body"), to_sync(inner) as adapter:
        adapter.send_message("hi")
        raise ValueError("body")
    assert inner.closed == 1
    assert inner.loops[0].is_closed()


def test_close_failure_still_closes_runner_and_prevents_reuse() -> None:
    inner = _Adapter()
    inner.close_error = True
    adapter = to_sync(inner)
    adapter.send_message("hi")
    with pytest.raises(ValueError, match="close failure"):
        adapter.close()
    assert inner.loops[0].is_closed()
    adapter.close()
    with pytest.raises(RuntimeError, match="closed"):
        adapter.send_message("after close")
    with pytest.raises(RuntimeError, match="closed"):
        adapter.reset_session("s")
    with pytest.raises(RuntimeError, match="closed"):
        adapter.__enter__()
    assert inner.closed == 1


def test_adapter_without_public_close_hook_needs_no_private_sdk_access() -> None:
    class MinimalAdapter:
        name = "minimal"

        async def send_message(
            self, prompt: str, *, session_id: str | None = None
        ) -> ChatbotResponse:
            return ChatbotResponse(text=prompt)

        async def reset_session(self, session_id: str) -> None:
            pass

    with to_sync(MinimalAdapter()) as adapter:
        assert adapter.send_message("hi").text == "hi"
    adapter.close()


@pytest.mark.parametrize("operation", ["send_message", "reset_session", "close", "__enter__"])
@pytest.mark.asyncio
async def test_running_loop_guard_precedes_coroutine_creation(
    operation: str, recwarn: pytest.WarningsRecorder
) -> None:
    inner = _Adapter()
    send = Mock(wraps=inner.send_message)
    reset = Mock(wraps=inner.reset_session)
    close = Mock(wraps=inner.aclose)
    inner.send_message = send  # type: ignore[method-assign]
    inner.reset_session = reset  # type: ignore[method-assign]
    inner.aclose = close  # type: ignore[method-assign]
    adapter = to_sync(inner)
    args = ("s",) if operation in {"send_message", "reset_session"} else ()
    with pytest.raises(RuntimeError, match="await the async adapter directly"):
        getattr(adapter, operation)(*args)
    send.assert_not_called()
    reset.assert_not_called()
    close.assert_not_called()
    gc.collect()
    assert not any("never awaited" in str(warning.message) for warning in recwarn)
    # No loop was initialized, so this guard-only wrapper owns no resources.


def test_cross_thread_use_fails_before_creating_coroutines() -> None:
    inner = _Adapter()
    send = Mock(wraps=inner.send_message)
    inner.send_message = send  # type: ignore[method-assign]
    with to_sync(inner) as adapter, ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(RuntimeError, match="same thread"):
            pool.submit(adapter.send_message, "wrong thread").result(timeout=5)
        with pytest.raises(RuntimeError, match="same thread"):
            pool.submit(adapter.close).result(timeout=5)
        send.assert_not_called()
        assert adapter.send_message("owner").text == "owner"


def test_real_responses_sdk_reuses_keepalive_connection_and_closes_on_owned_loop() -> None:
    sdk = pytest.importorskip("openai")
    requests: list[dict[str, Any]] = []
    peers: list[tuple[str, int]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, message_format: str, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            assert self.path == "/v1/responses"
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            peers.append(self.client_address)
            assert request["store"] is False
            body = json.dumps(
                {
                    "id": "resp_bridge",
                    "object": "response",
                    "created_at": 1,
                    "model": "contract-model",
                    "status": "completed",
                    "error": None,
                    "incomplete_details": None,
                    "output": [
                        {
                            "id": "msg_bridge",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "Local reply.",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    client = sdk.AsyncOpenAI(
        api_key="synthetic-bridge-contract-value",  # pragma: allowlist secret
        base_url=f"http://127.0.0.1:{server.server_port}/v1",
        max_retries=0,
        timeout=5,
    )

    class CallerOwnedAdapter(AsyncOpenAIResponsesAdapter):
        async def aclose(self) -> None:
            # This adapter explicitly owns the injected test client.
            await client.close()

    try:
        with to_sync(CallerOwnedAdapter(client=client)) as adapter:
            assert adapter.send_message("one", session_id="s").text == "Local reply."
            assert adapter.send_message("two", session_id="s").text == "Local reply."
            assert len(requests[1]["input"]) == 3
            adapter.reset_session("s")
            adapter.send_message("fresh", session_id="s")
            assert requests[-1]["input"] == [{"role": "user", "content": "fresh"}]
        assert client.is_closed()
        assert len(peers) == 3 and len(set(peers)) == 1
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
