"""Anthropic Messages adapter (sync + async).

Requires the `[anthropic]` extra:

    pip install "pytest-wardenbot[anthropic]"

Both adapters support optional session-keyed conversation memory: pass
`session_id` to `send_message` and the adapter accumulates user/assistant
turns. Calling `reset_session(session_id)` drops the stored turns.

The Anthropic Messages API distinguishes between the system prompt (a
top-level `system` parameter) and the conversation `messages` array (which
contains only user and assistant turns). The adapter handles this naturally:
`system_prompt` is sent as the `system` argument on every call; messages
contains only the alternating user/assistant turns.

A user-supplied client can be injected via the `client` parameter for tests
and custom configuration.
"""

from __future__ import annotations

import time
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse

_INSTALL_HINT = (
    "AnthropicMessagesAdapter requires the [anthropic] extra. "
    "Install with: pip install 'pytest-wardenbot[anthropic]'"
)


def _import_anthropic() -> Any:
    try:
        import anthropic  # type: ignore[import-not-found]

        return anthropic
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


def _extract_text(message: Any) -> str:
    """Pull the assistant text from an Anthropic Message response.

    Anthropic responses contain a list of content blocks; for normal text
    generation the first block has a `text` attribute. Concatenates all text
    blocks (some responses can split text across blocks).
    """
    try:
        blocks = message.content
    except AttributeError as exc:
        raise WardenBotInfraError(f"Anthropic response missing .content. Got: {message!r}") from exc

    text_parts: list[str] = []
    for block in blocks:
        block_text = getattr(block, "text", None)
        if isinstance(block_text, str):
            text_parts.append(block_text)
    return "".join(text_parts)


def _message_to_raw(message: Any) -> dict[str, Any]:
    """Best-effort dict view of an Anthropic message for ChatbotResponse.raw."""
    if hasattr(message, "model_dump"):
        return message.model_dump()
    if isinstance(message, dict):
        return message
    return {"repr": repr(message)}


class AnthropicMessagesAdapter:
    """Synchronous Anthropic Messages adapter.

    Example:

    ```python
    @pytest.fixture
    def chatbot():
        return AnthropicMessagesAdapter(
            model="claude-haiku-4-5",
            system_prompt="You are a customer-support assistant for Example Corp.",
        )
    ```
    """

    name = "anthropic-messages"
    stateful = True  # accumulates per-session_id history; multi-turn priming lands

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5",
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        client: Any | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        if client is None:
            anthropic = _import_anthropic()
            client = anthropic.Anthropic()
        self._client: Any = client
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._extra_request_fields = dict(extra_request_fields or {})
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._sessions: dict[str, list[dict[str, str]]] = {}

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        history = self._sessions.setdefault(session_id, []) if session_id else []
        messages = [*history, {"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages,
            **self._extra_request_fields,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        start = time.perf_counter()
        try:
            message = self._client.messages.create(**kwargs)
        except Exception as exc:
            raise WardenBotInfraError(
                f"Anthropic API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _extract_text(message)
        if session_id is not None:
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text})

        raw = _message_to_raw(message)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __repr__(self) -> str:
        return f"AnthropicMessagesAdapter(model={self._model!r})"


class AsyncAnthropicMessagesAdapter:
    """Async counterpart to `AnthropicMessagesAdapter`.

    Same shape, same error wrapping, same redaction default. Uses
    `anthropic.AsyncAnthropic`.
    """

    name = "async-anthropic-messages"
    stateful = True  # accumulates per-session_id history; multi-turn priming lands

    def __init__(
        self,
        *,
        model: str = "claude-haiku-4-5",
        system_prompt: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        client: Any | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        if client is None:
            anthropic = _import_anthropic()
            client = anthropic.AsyncAnthropic()
        self._client: Any = client
        self._model = model
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._extra_request_fields = dict(extra_request_fields or {})
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._sessions: dict[str, list[dict[str, str]]] = {}

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        history = self._sessions.setdefault(session_id, []) if session_id else []
        messages = [*history, {"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "messages": messages,
            **self._extra_request_fields,
        }
        if self._system_prompt:
            kwargs["system"] = self._system_prompt

        start = time.perf_counter()
        try:
            message = await self._client.messages.create(**kwargs)
        except Exception as exc:
            raise WardenBotInfraError(
                f"Anthropic API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _extract_text(message)
        if session_id is not None:
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text})

        raw = _message_to_raw(message)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __repr__(self) -> str:
        return f"AsyncAnthropicMessagesAdapter(model={self._model!r})"
