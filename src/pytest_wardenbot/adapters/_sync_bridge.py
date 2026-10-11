"""Drive an async chatbot from synchronous tests on one persistent event loop.

Use the bridge as a context manager so its event loop and the adapter's public
``aclose()`` hook are cleaned up on the same loop::

    @pytest.fixture
    def chatbot():
        with to_sync(AsyncOpenAIResponsesAdapter()) as adapter:
            yield adapter

Create and use each bridge on one thread, outside running event loops. An async
adapter already used on another loop must not be moved into a bridge. Prefer
direct async calls inside async tests. Injected client ownership is determined
by the wrapped adapter, not by this bridge. Adapters without a public ``aclose``
hook retain responsibility for their other resources.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from pytest_wardenbot.adapters.base import AsyncChatbotAdapter, ChatbotResponse

_Result = TypeVar("_Result")


class _SyncFromAsyncAdapter:
    """Sync facade with one thread-owned loop and explicit cleanup."""

    def __init__(self, inner: AsyncChatbotAdapter) -> None:
        self._inner = inner
        self._runner = asyncio.Runner()
        self._thread = threading.current_thread()
        self._closed = False
        self.name = f"sync-from-async({inner.name})"
        self.stateful = getattr(inner, "stateful", False)

    def _check_usable(self) -> None:
        if self._closed:
            raise RuntimeError("The to_sync bridge is closed; create a new bridge.")
        if threading.current_thread() is not self._thread:
            raise RuntimeError("Create and use each to_sync bridge on the same thread.")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise RuntimeError(
            "Do not use to_sync inside a running event loop; await the async adapter directly."
        )

    def _run(self, operation: Callable[[], Coroutine[Any, Any, _Result]]) -> _Result:
        self._check_usable()  # Reject invalid calls before creating a coroutine.
        coroutine = operation()
        try:
            return self._runner.run(coroutine)
        finally:
            # Runner can reject a coroutine before starting it. Closing an
            # already completed coroutine is harmless and avoids leaked ones.
            coroutine.close()

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        return self._run(lambda: self._inner.send_message(prompt, session_id=session_id))

    def reset_session(self, session_id: str) -> None:
        self._run(lambda: self._inner.reset_session(session_id))

    def close(self) -> None:
        """Run public ``aclose`` on the owned loop, then always close that loop.

        Idempotent after cleanup. Errors from the adapter's close hook propagate,
        while the runner is still closed. No private SDK clients are inspected.
        """
        if self._closed:
            return
        self._check_usable()
        try:
            close = getattr(self._inner, "aclose", None)
            if callable(close):

                async def close_inner() -> None:
                    result = close()
                    if not inspect.isawaitable(result):
                        raise TypeError("The adapter's aclose() hook must return an awaitable.")
                    await result

                self._run(close_inner)
        finally:
            self._closed = True
            self._runner.close()

    def __enter__(self) -> _SyncFromAsyncAdapter:
        self._check_usable()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def to_sync(adapter: AsyncChatbotAdapter) -> _SyncFromAsyncAdapter:
    """Wrap an async adapter using a persistent ``asyncio.Runner`` event loop.

    Use ``with to_sync(adapter) as chatbot:`` or call ``close()`` explicitly.
    The bridge supports repeated sends and resets on the same thread. It rejects
    calls from running event loops before creating coroutines. Close invokes the
    adapter's public ``aclose()`` hook when available; injected client ownership
    remains the wrapped adapter's policy.
    """
    return _SyncFromAsyncAdapter(adapter)
