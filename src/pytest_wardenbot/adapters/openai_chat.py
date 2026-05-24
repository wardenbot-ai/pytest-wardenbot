"""OpenAI Chat Completions adapter (sync + async).

Requires the `[openai]` extra:

    pip install "pytest-wardenbot[openai]"

Both adapters support optional session-keyed conversation memory: pass
`session_id` to `send_message` and the adapter accumulates user/assistant turns
keyed by that ID. The shipped multi-turn jailbreak test uses this to chain
priming prompts before the payload. Calling `reset_session(session_id)` drops
the stored turns for that ID. Without a `session_id`, every call is stateless.

A user-supplied OpenAI client can be injected via the `client` parameter for
tests and custom configuration (custom base_url, proxy, alternate auth).
"""

from __future__ import annotations

import time
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse

_INSTALL_HINT = (
    "OpenAIChatAdapter requires the [openai] extra. "
    "Install with: pip install 'pytest-wardenbot[openai]'"
)


def _import_openai() -> Any:
    try:
        import openai  # type: ignore[import-not-found]

        return openai
    except ImportError as exc:
        raise ImportError(_INSTALL_HINT) from exc


def _build_messages(
    history: list[dict[str, str]],
    prompt: str,
    system_prompt: str | None,
) -> list[dict[str, str]]:
    """Construct the message list for one Chat Completions call.

    Includes the system prompt iff history is empty (first turn of a session
    or a stateless call).
    """
    messages: list[dict[str, str]] = []
    if not history and system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(history)
    messages.append({"role": "user", "content": prompt})
    return messages


def _extract_text(completion: Any) -> str:
    """Pull the assistant text from an OpenAI Chat Completion response."""
    try:
        text = completion.choices[0].message.content
    except (AttributeError, IndexError) as exc:
        raise WardenBotInfraError(
            f"OpenAI response missing choices[0].message.content. Got: {completion!r}"
        ) from exc
    return text or ""


def _completion_to_raw(completion: Any) -> dict[str, Any]:
    """Best-effort dict view of an OpenAI completion for ChatbotResponse.raw."""
    if hasattr(completion, "model_dump"):
        return completion.model_dump()
    if isinstance(completion, dict):
        return completion
    return {"repr": repr(completion)}


class OpenAIChatAdapter:
    """Synchronous OpenAI Chat Completions adapter.

    Example:

    ```python
    @pytest.fixture
    def chatbot():
        return OpenAIChatAdapter(
            model="gpt-4o-mini",
            system_prompt="You are a customer-support assistant for Example Corp.",
        )
    ```

    Response payloads stored in `ChatbotResponse.raw` are redacted by default.
    Pass `keep_sensitive_response_fields=True` to keep the unredacted payload.
    """

    name = "openai-chat"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        system_prompt: str | None = None,
        temperature: float = 0.0,
        client: Any | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        if client is None:
            openai = _import_openai()
            client = openai.OpenAI()
        self._client: Any = client
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._extra_request_fields = dict(extra_request_fields or {})
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._sessions: dict[str, list[dict[str, str]]] = {}

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        history = self._sessions.setdefault(session_id, []) if session_id else []
        messages = _build_messages(history, prompt, self._system_prompt)

        start = time.perf_counter()
        try:
            completion = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                **self._extra_request_fields,
            )
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _extract_text(completion)
        if session_id is not None:
            if not history and self._system_prompt:
                history.append({"role": "system", "content": self._system_prompt})
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text})

        raw = _completion_to_raw(completion)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __repr__(self) -> str:
        return f"OpenAIChatAdapter(model={self._model!r})"


class AsyncOpenAIChatAdapter:
    """Async counterpart to `OpenAIChatAdapter`.

    Same shape, same error wrapping, same redaction default. Uses
    `openai.AsyncOpenAI`. Useful for parallel fan-out in user-written async
    test suites; the shipped v0.1 tests are sync, so pass through
    `to_sync(...)` to consume this from the default `chatbot` fixture.
    """

    name = "async-openai-chat"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        system_prompt: str | None = None,
        temperature: float = 0.0,
        client: Any | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        if client is None:
            openai = _import_openai()
            client = openai.AsyncOpenAI()
        self._client: Any = client
        self._model = model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._extra_request_fields = dict(extra_request_fields or {})
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._sessions: dict[str, list[dict[str, str]]] = {}

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        history = self._sessions.setdefault(session_id, []) if session_id else []
        messages = _build_messages(history, prompt, self._system_prompt)

        start = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                **self._extra_request_fields,
            )
        except Exception as exc:
            raise WardenBotInfraError(
                f"OpenAI API call failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _extract_text(completion)
        if session_id is not None:
            if not history and self._system_prompt:
                history.append({"role": "system", "content": self._system_prompt})
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": text})

        raw = _completion_to_raw(completion)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def __repr__(self) -> str:
        return f"AsyncOpenAIChatAdapter(model={self._model!r})"
