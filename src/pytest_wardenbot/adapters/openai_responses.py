"""Text-only OpenAI Responses adapters with local conversation memory.

Requires ``pytest-wardenbot[openai]`` (OpenAI SDK >= 1.66.3). Requests always
use ``store=False``; they never create Conversations or chain response IDs.
Each session replays its user messages and complete returned output items,
including encrypted reasoning. Instructions are supplied on every request.
``reset_session`` clears local history only; it does not delete remote data
or change the provider's other retention policies.

Completed assistant text and refusals are supported. Tools, streaming,
background responses, and incomplete responses require another adapter.
Temperature is omitted unless explicitly supplied, for model compatibility.
Sensitive fields, including encrypted reasoning, are redacted from public
``raw`` payloads unless ``keep_sensitive_response_fields=True`` is supplied.

Injected clients belong to their caller. For internally created clients, call
``close()`` or ``await aclose()`` to release their connections. SDK exceptions
are deliberately suppressed in public tracebacks to avoid exposing response
bodies or credentials; infrastructure errors identify the exception type.

API guidance: https://developers.openai.com/api/docs/guides/conversation-state
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import DEFAULT_SENSITIVE_FIELD_PARTS, redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse

_INSTALL_HINT = (
    "OpenAIResponsesAdapter requires OpenAI SDK >= 1.66.3. "
    "Install with: pip install 'pytest-wardenbot[openai]'"
)

# extra_body is merged into the SDK's JSON body and can bypass every other
# check here. Reject it, along with state/tool/stream controls we manage.
_RESERVED_FIELDS = frozenset(
    {
        "model",
        "input",
        "instructions",
        "temperature",
        "store",
        "session_id",
        "previous_response_id",
        "conversation",
        "stream",
        "stream_options",
        "background",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "max_tool_calls",
        "prompt",
        "extra_body",
    }
)


def _import_openai() -> Any:
    try:
        import openai  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc
    return openai


@dataclass
class _SyncSession:
    history: list[dict[str, Any]] = field(default_factory=list)
    lock: Any = field(default_factory=threading.Lock)
    users: int = 0


class _SyncSessions:
    def __init__(self) -> None:
        self._states: dict[str, _SyncSession] = {}
        self._registry_lock = threading.Lock()

    @contextmanager
    def state(self, session_id: str) -> Iterator[_SyncSession]:
        # Count queued callers too: a reset must not replace a lock while
        # another sender is waiting on it. Registry locking never spans I/O.
        with self._registry_lock:
            state = self._states.setdefault(session_id, _SyncSession())
            state.users += 1
        try:
            with state.lock:
                yield state
        finally:
            with self._registry_lock:
                state.users -= 1
                if not state.users and not state.history:
                    self._states.pop(session_id, None)


@dataclass
class _AsyncSession:
    history: list[dict[str, Any]] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class _AsyncSessions:
    def __init__(self) -> None:
        self._states: dict[str, _AsyncSession] = {}

    @asynccontextmanager
    async def state(self, session_id: str) -> AsyncIterator[_AsyncSession]:
        # These registry updates do not await, so are atomic on the adapter's
        # event loop. Like AsyncOpenAI, this adapter belongs to one event loop.
        state = self._states.setdefault(session_id, _AsyncSession())
        state.users += 1
        try:
            async with state.lock:
                yield state
        finally:
            state.users -= 1
            if not state.users and not state.history:
                self._states.pop(session_id, None)


_SessionStore = TypeVar("_SessionStore", _SyncSessions, _AsyncSessions)


def _validated_response(response: Any) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """Validate all output before accepting any text or committing history."""
    try:
        raw = deepcopy(
            response
            if isinstance(response, dict)
            else response.model_dump(mode="json", by_alias=True, exclude_unset=True)
        )
    except Exception:
        raise WardenBotInfraError(
            "OpenAI Responses returned an unreadable response payload."
        ) from None
    if not isinstance(raw, dict):
        raise WardenBotInfraError("OpenAI Responses returned a non-object response payload.")
    if raw.get("status") != "completed" or raw.get("error") is not None:
        raise WardenBotInfraError("OpenAI Responses returned a non-completed or failed response.")
    if raw.get("incomplete_details") is not None:
        raise WardenBotInfraError("OpenAI Responses returned incomplete output.")
    output = raw.get("output")
    if not isinstance(output, list) or not output:
        raise WardenBotInfraError("OpenAI Responses returned no assistant output.")

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise WardenBotInfraError("OpenAI Responses returned a malformed output item.")
        kind = item.get("type")
        if kind == "reasoning":
            if item.get("status") not in (None, "completed"):
                raise WardenBotInfraError("OpenAI Responses returned incomplete reasoning.")
            if not isinstance(item.get("summary"), list):
                raise WardenBotInfraError("OpenAI Responses returned malformed reasoning.")
            if any(
                not isinstance(summary, dict)
                or summary.get("type") != "summary_text"
                or not isinstance(summary.get("text"), str)
                for summary in item["summary"]
            ) or (
                item.get("encrypted_content") is not None
                and not isinstance(item["encrypted_content"], str)
            ):
                raise WardenBotInfraError("OpenAI Responses returned malformed reasoning content.")
            continue
        if kind != "message":
            raise WardenBotInfraError(
                "OpenAI Responses returned an unsupported output item; "
                "this adapter supports text and refusals without tools."
            )
        if item.get("role") != "assistant" or item.get("status") != "completed":
            raise WardenBotInfraError("OpenAI Responses returned an incomplete assistant message.")
        content = item.get("content")
        if not isinstance(content, list) or not content:
            raise WardenBotInfraError("OpenAI Responses returned malformed assistant content.")
        for part in content:
            if not isinstance(part, dict):
                raise WardenBotInfraError("OpenAI Responses returned malformed assistant content.")
            if part.get("type") == "output_text":
                value = part.get("text")
            elif part.get("type") == "refusal":
                value = part.get("refusal")
            else:
                raise WardenBotInfraError(
                    "OpenAI Responses returned unsupported assistant content."
                )
            if not isinstance(value, str):
                raise WardenBotInfraError("OpenAI Responses returned non-text assistant content.")
            parts.append(value)
    text = "".join(parts)
    if not text:
        raise WardenBotInfraError("OpenAI Responses returned no assistant text or refusal.")
    return text, raw, deepcopy(output)


class _ResponsesAdapterBase(Generic[_SessionStore]):
    stateful = True
    _client_factory_name = "OpenAI"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        system_prompt: str | None = None,
        temperature: float | None = None,
        client: Any | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        extras = deepcopy(extra_request_fields or {})
        if _RESERVED_FIELDS.intersection(extras):
            raise ValueError("extra_request_fields contains reserved Responses request fields.")
        include = extras.pop("include", [])
        if not isinstance(include, list) or not all(isinstance(value, str) for value in include):
            raise ValueError("The Responses include field must be a list of strings.")
        extras["include"] = list(dict.fromkeys(["reasoning.encrypted_content", *include]))
        self._owns_client = client is None
        if client is None:
            openai = _import_openai()
            factory = getattr(openai, self._client_factory_name, None)
            if not callable(factory):
                raise ImportError(_INSTALL_HINT)
            client = factory()
        if not callable(getattr(getattr(client, "responses", None), "create", None)):
            if self._owns_client:
                raise ImportError(_INSTALL_HINT)
            raise ValueError("The injected client must provide responses.create().")
        self._client: Any = client
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._extra_request_fields = extras
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._sessions: _SessionStore = self._make_sessions()

    def _make_sessions(self) -> _SessionStore:
        raise NotImplementedError

    def _request(self, prompt: str, history: list[dict[str, Any]]) -> dict[str, Any]:
        request = deepcopy(self._extra_request_fields)
        request.update(
            model=self._model,
            input=[*deepcopy(history), {"role": "user", "content": prompt}],
            store=False,
        )
        if self._system_prompt is not None:
            request["instructions"] = self._system_prompt
        if self._temperature is not None:
            request["temperature"] = self._temperature
        return request

    def _result(
        self, response: Any, elapsed_ms: float
    ) -> tuple[ChatbotResponse, list[dict[str, Any]]]:
        text, raw, output = _validated_response(response)
        stored_raw = (
            raw
            if self._keep_sensitive_response_fields
            else redact_response_payload(
                raw, sensitive_parts=(*DEFAULT_SENSITIVE_FIELD_PARTS, "encrypted_content")
            )
        )
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms), output


class OpenAIResponsesAdapter(_ResponsesAdapterBase[_SyncSessions]):
    """Synchronous Responses adapter with isolated, locally managed sessions.

    Calls for one session (including the empty-string ID) are serialized with
    resets. Different sessions and calls without an ID can run concurrently.
    A failed request does not enter the conversation history.
    """

    name = "openai-responses"

    def _make_sessions(self) -> _SyncSessions:
        return _SyncSessions()

    def _send(
        self, prompt: str, history: list[dict[str, Any]]
    ) -> tuple[ChatbotResponse, list[dict[str, Any]]]:
        request = self._request(prompt, history)
        start = time.perf_counter()
        try:
            response = self._client.responses.create(**request)
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI Responses API call failed ({type(exc).__name__})."
            ) from None
        return self._result(response, (time.perf_counter() - start) * 1000)

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        if session_id is None:
            return self._send(prompt, [])[0]
        with self._sessions.state(session_id) as state:
            result, output = self._send(prompt, state.history)
            state.history.extend([{"role": "user", "content": prompt}, *output])
            return result

    def reset_session(self, session_id: str) -> None:
        """Wait for preceding calls, then clear this session's local history."""
        with self._sessions.state(session_id) as state:
            state.history.clear()

    def close(self) -> None:
        """Close an internally created client; injected clients remain caller-owned."""
        if self._owns_client:
            self._client.close()

    def __repr__(self) -> str:
        return f"OpenAIResponsesAdapter(model={self._model!r})"


class AsyncOpenAIResponsesAdapter(_ResponsesAdapterBase[_AsyncSessions]):
    """Async Responses adapter; use on one event loop, or wrap with ``to_sync``.

    Per-session locks serialize sends and resets without blocking unrelated
    sessions. Cancellation propagates and never appends a partial turn.
    """

    name = "async-openai-responses"
    _client_factory_name = "AsyncOpenAI"

    def _make_sessions(self) -> _AsyncSessions:
        return _AsyncSessions()

    async def _send(
        self, prompt: str, history: list[dict[str, Any]]
    ) -> tuple[ChatbotResponse, list[dict[str, Any]]]:
        request = self._request(prompt, history)
        start = time.perf_counter()
        try:
            response = await self._client.responses.create(**request)
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI Responses API call failed ({type(exc).__name__})."
            ) from None
        return self._result(response, (time.perf_counter() - start) * 1000)

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        if session_id is None:
            return (await self._send(prompt, []))[0]
        async with self._sessions.state(session_id) as state:
            result, output = await self._send(prompt, state.history)
            state.history.extend([{"role": "user", "content": prompt}, *output])
            return result

    async def reset_session(self, session_id: str) -> None:
        """Wait for preceding calls, then clear this session's local history."""
        async with self._sessions.state(session_id) as state:
            state.history.clear()

    async def aclose(self) -> None:
        """Close an internally created client; injected clients remain caller-owned."""
        if self._owns_client:
            await self._client.close()

    def __repr__(self) -> str:
        return f"AsyncOpenAIResponsesAdapter(model={self._model!r})"
