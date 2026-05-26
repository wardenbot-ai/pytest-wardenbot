"""Wrap an `AsyncChatbotAdapter` so it satisfies the sync `ChatbotAdapter`.

The shipped tests in v0.1 are synchronous. Users whose chatbots are behind
async transports can still drive the shipped tests by passing their async
adapter through `to_sync(...)` in their `chatbot` fixture:

    from pytest_wardenbot.adapters import to_sync
    from pytest_wardenbot.adapters.openai_chat import AsyncOpenAIChatAdapter

    @pytest.fixture
    def chatbot():
        return to_sync(AsyncOpenAIChatAdapter())

The bridge uses `asyncio.run` per call. That precludes use from inside a
running event loop (pytest-asyncio tests, for example) — `asyncio.run` will
raise. In that case, drive the async adapter directly from an async test.
"""

from __future__ import annotations

import asyncio

from pytest_wardenbot.adapters.base import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
)


class _SyncFromAsyncAdapter:
    """Internal adapter wrapping an async adapter behind the sync Protocol."""

    def __init__(self, inner: AsyncChatbotAdapter) -> None:
        self._inner = inner
        self.name = f"sync-from-async({inner.name})"
        # Propagate the wrapped adapter's statefulness so the multi-turn test's
        # session-awareness warning reflects the real adapter, not the wrapper.
        self.stateful = getattr(inner, "stateful", False)

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        return asyncio.run(self._inner.send_message(prompt, session_id=session_id))

    def reset_session(self, session_id: str) -> None:
        asyncio.run(self._inner.reset_session(session_id))


def to_sync(adapter: AsyncChatbotAdapter) -> ChatbotAdapter:
    """Return a `ChatbotAdapter` that delegates each call to the async adapter.

    Uses `asyncio.run` per call. Raises `RuntimeError` if called from inside
    a running event loop — in that case, use the async adapter directly from
    an async test instead of wrapping it.
    """
    return _SyncFromAsyncAdapter(adapter)
