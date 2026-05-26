"""OpenAI Assistants API adapter (sync + async).

Requires the ``[openai]`` extra::

    pip install "pytest-wardenbot[openai]"

.. warning::

    OpenAI's Assistants API is **deprecated** (sunset 2026-08-26); the forward
    path is the Responses API. This adapter is a stopgap so teams still running
    on Assistants can test their bots today. Constructing either adapter emits a
    ``DeprecationWarning``. Plan the migration to the Responses API (and
    ``OpenAIChatAdapter``) before the sunset.

``session_id`` maps to an OpenAI **thread**: pass it to keep multi-turn context
across calls, omit it for a stateless one-shot (a throwaway thread is created
for the call and deleted afterwards). ``reset_session(session_id)`` deletes the
thread bound to that ID. A user-supplied client can be injected via ``client``
for tests / custom configuration (custom base_url, proxy, alternate auth).

This adapter tests the assistant's *text* behaviour. If a run pauses for tool
outputs (``requires_action``), the adapter raises ``WardenBotInfraError`` rather
than attempting to drive the tools.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import warnings
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse

_INSTALL_HINT = (
    "OpenAIAssistantsAdapter requires the [openai] extra. "
    "Install with: pip install 'pytest-wardenbot[openai]'"
)

_DEPRECATION_MESSAGE = (
    "OpenAI's Assistants API is deprecated (sunset 2026-08-26). "
    "OpenAIAssistantsAdapter is a stopgap; migrate to the Responses API "
    "(and OpenAIChatAdapter) before the sunset."
)

# Run statuses that mean the run has finished, for better or worse.
_TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "expired", "incomplete"})


def _import_openai() -> Any:
    try:
        import openai  # type: ignore[import-not-found]

        return openai
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


def _extract_text(message: Any) -> str:
    """Pull assistant text from the latest Assistants API thread message."""
    try:
        blocks = list(message.content)
    except (AttributeError, TypeError) as exc:
        raise WardenBotInfraError(
            f"OpenAI Assistants response shape unexpected: {message!r}"
        ) from exc
    for block in blocks:
        text_obj = getattr(block, "text", None)
        if text_obj is not None:
            return getattr(text_obj, "value", "") or ""
    raise WardenBotInfraError(
        f"OpenAI Assistants message had no text content block. Got: {message!r}"
    )


def _message_to_raw(message: Any) -> dict[str, Any]:
    """Best-effort dict view of an Assistants message for ChatbotResponse.raw."""
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if isinstance(message, dict):
        return message
    return {"repr": repr(message)}


def _check_completed(run: Any) -> None:
    """Raise if a terminal run did not complete successfully."""
    if run.status != "completed":
        last_error = getattr(run, "last_error", None)
        raise WardenBotInfraError(
            f"OpenAI Assistants run ended with status {run.status!r}: {last_error!r}"
        )


def _requires_action_error() -> WardenBotInfraError:
    return WardenBotInfraError(
        "OpenAI Assistants run requires tool outputs (requires_action); this "
        "adapter tests text behaviour and does not drive tools."
    )


def _timeout_error(timeout_s: float, status: str) -> WardenBotInfraError:
    return WardenBotInfraError(
        f"OpenAI Assistants run did not complete within {timeout_s}s (last status: {status!r})."
    )


class OpenAIAssistantsAdapter:
    """Synchronous OpenAI Assistants API adapter (deprecated API; see module docs).

    Example::

        @pytest.fixture
        def chatbot():
            return OpenAIAssistantsAdapter(assistant_id="asst_...")

    Response payloads stored in ``ChatbotResponse.raw`` are redacted by default;
    pass ``keep_sensitive_response_fields=True`` to keep the unredacted payload.
    """

    name = "openai-assistants"
    stateful = True  # session_id maps to a persistent thread; multi-turn priming lands

    def __init__(
        self,
        *,
        assistant_id: str,
        client: Any | None = None,
        timeout_s: float = 60.0,
        poll_interval_s: float = 0.5,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
        if client is None:
            openai = _import_openai()
            client = openai.OpenAI()
        self._client: Any = client
        self._assistant_id = assistant_id
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._threads: dict[str, str] = {}

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        ephemeral = session_id is None
        thread_id: str | None = None
        threads = self._client.beta.threads

        start = time.perf_counter()
        try:
            thread_id = self._resolve_thread(session_id)
            threads.messages.create(thread_id=thread_id, role="user", content=prompt)
            run = threads.runs.create(thread_id=thread_id, assistant_id=self._assistant_id)
            self._poll_run(thread_id, run)
            message = self._latest_assistant_message(thread_id)
            text = _extract_text(message)
            raw = _message_to_raw(message)
        except WardenBotInfraError:
            raise
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI Assistants API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if ephemeral and thread_id is not None:
                self._delete_thread(thread_id)
        elapsed_ms = (time.perf_counter() - start) * 1000

        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        thread_id = self._threads.pop(session_id, None)
        if thread_id is not None:
            self._delete_thread(thread_id)

    def _resolve_thread(self, session_id: str | None) -> str:
        threads = self._client.beta.threads
        if session_id is None:
            return threads.create().id
        thread_id = self._threads.get(session_id)
        if thread_id is None:
            thread_id = threads.create().id
            self._threads[session_id] = thread_id
        return thread_id

    def _poll_run(self, thread_id: str, run: Any) -> None:
        deadline = time.monotonic() + self._timeout_s
        while run.status not in _TERMINAL_STATES:
            if run.status == "requires_action":
                raise _requires_action_error()
            if time.monotonic() >= deadline:
                raise _timeout_error(self._timeout_s, run.status)
            time.sleep(self._poll_interval_s)
            run = self._client.beta.threads.runs.retrieve(run_id=run.id, thread_id=thread_id)
        _check_completed(run)

    def _latest_assistant_message(self, thread_id: str) -> Any:
        messages = self._client.beta.threads.messages.list(
            thread_id=thread_id, order="desc", limit=1
        )
        data = list(getattr(messages, "data", None) or [])
        if not data:
            raise WardenBotInfraError(
                f"OpenAI Assistants thread {thread_id!r} had no messages after the run completed."
            )
        message = data[0]
        if getattr(message, "role", "assistant") != "assistant":
            raise WardenBotInfraError(
                f"OpenAI Assistants thread {thread_id!r}: latest message role is "
                f"{getattr(message, 'role', None)!r}, not an assistant reply."
            )
        return message

    def _delete_thread(self, thread_id: str) -> None:
        with contextlib.suppress(Exception):
            self._client.beta.threads.delete(thread_id)

    def __repr__(self) -> str:
        return f"OpenAIAssistantsAdapter(assistant_id={self._assistant_id!r})"


class AsyncOpenAIAssistantsAdapter:
    """Async counterpart to ``OpenAIAssistantsAdapter`` (deprecated API; see module docs).

    Same shape, error wrapping, and redaction default; uses ``openai.AsyncOpenAI``.
    """

    name = "async-openai-assistants"
    stateful = True  # session_id maps to a persistent thread; multi-turn priming lands

    def __init__(
        self,
        *,
        assistant_id: str,
        client: Any | None = None,
        timeout_s: float = 60.0,
        poll_interval_s: float = 0.5,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        warnings.warn(_DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)
        if client is None:
            openai = _import_openai()
            client = openai.AsyncOpenAI()
        self._client: Any = client
        self._assistant_id = assistant_id
        self._timeout_s = timeout_s
        self._poll_interval_s = poll_interval_s
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._threads: dict[str, str] = {}

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        ephemeral = session_id is None
        thread_id: str | None = None
        threads = self._client.beta.threads

        start = time.perf_counter()
        try:
            thread_id = await self._resolve_thread(session_id)
            await threads.messages.create(thread_id=thread_id, role="user", content=prompt)
            run = await threads.runs.create(thread_id=thread_id, assistant_id=self._assistant_id)
            await self._poll_run(thread_id, run)
            message = await self._latest_assistant_message(thread_id)
            text = _extract_text(message)
            raw = _message_to_raw(message)
        except WardenBotInfraError:
            raise
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI Assistants API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            if ephemeral and thread_id is not None:
                await self._delete_thread(thread_id)
        elapsed_ms = (time.perf_counter() - start) * 1000

        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        thread_id = self._threads.pop(session_id, None)
        if thread_id is not None:
            await self._delete_thread(thread_id)

    async def _resolve_thread(self, session_id: str | None) -> str:
        threads = self._client.beta.threads
        if session_id is None:
            return (await threads.create()).id
        thread_id = self._threads.get(session_id)
        if thread_id is None:
            thread_id = (await threads.create()).id
            self._threads[session_id] = thread_id
        return thread_id

    async def _poll_run(self, thread_id: str, run: Any) -> None:
        deadline = time.monotonic() + self._timeout_s
        while run.status not in _TERMINAL_STATES:
            if run.status == "requires_action":
                raise _requires_action_error()
            if time.monotonic() >= deadline:
                raise _timeout_error(self._timeout_s, run.status)
            await asyncio.sleep(self._poll_interval_s)
            run = await self._client.beta.threads.runs.retrieve(run_id=run.id, thread_id=thread_id)
        _check_completed(run)

    async def _latest_assistant_message(self, thread_id: str) -> Any:
        messages = await self._client.beta.threads.messages.list(
            thread_id=thread_id, order="desc", limit=1
        )
        data = list(getattr(messages, "data", None) or [])
        if not data:
            raise WardenBotInfraError(
                f"OpenAI Assistants thread {thread_id!r} had no messages after the run completed."
            )
        message = data[0]
        if getattr(message, "role", "assistant") != "assistant":
            raise WardenBotInfraError(
                f"OpenAI Assistants thread {thread_id!r}: latest message role is "
                f"{getattr(message, 'role', None)!r}, not an assistant reply."
            )
        return message

    async def _delete_thread(self, thread_id: str) -> None:
        with contextlib.suppress(Exception):
            await self._client.beta.threads.delete(thread_id)

    def __repr__(self) -> str:
        return f"AsyncOpenAIAssistantsAdapter(assistant_id={self._assistant_id!r})"
