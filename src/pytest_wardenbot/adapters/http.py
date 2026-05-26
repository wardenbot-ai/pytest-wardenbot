"""Generic HTTP chatbot adapter.

Posts a JSON payload to a chatbot endpoint. The request and response shapes are
configurable so this works with most homegrown chatbot APIs without writing a
custom adapter.

For OpenAI / Anthropic, prefer the dedicated adapters
(`pytest_wardenbot.adapters.openai_chat`, `pytest_wardenbot.adapters.anthropic_msgs`).

All transport, status, and shape errors are wrapped in `WardenBotInfraError`
so they propagate as pytest ERRORs (not FAILUREs) — distinguishing "your bot
is unreachable" from "your bot failed a security check".
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse


class HTTPChatbotAdapter:
    """Generic HTTP-POST chatbot adapter.

    Example:

    ```python
    @pytest.fixture
    def chatbot():
        return HTTPChatbotAdapter(
            url="https://api.example.com/chat",
            headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
            request_field="message",
            response_field="response",
        )
    ```

    For non-standard response shapes, pass a callable to `response_field`
    that extracts the text from the nested response dict — for example,
    selecting the first choice's message content from an OpenAI-style
    response body.

    Response payloads stored in `ChatbotResponse.raw` are redacted by default:
    any dict key containing `authorization`, `api-key`, `cookie`, etc. has its
    value replaced with `[REDACTED]`. Pass `keep_sensitive_response_fields=True`
    to disable (debugging a vendor response shape, etc.).
    """

    name = "http"

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        request_field: str = "message",
        response_field: str | Callable[[dict[str, Any]], str] = "response",
        extra_request_fields: dict[str, Any] | None = None,
        timeout: float = 30.0,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        self._url = url
        self._headers = dict(headers or {})
        self._request_field = request_field
        self._response_field = response_field
        self._extra_request_fields = dict(extra_request_fields or {})
        self._timeout = timeout
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._client = httpx.Client(timeout=timeout)

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        payload: dict[str, Any] = {
            self._request_field: prompt,
            **self._extra_request_fields,
        }
        if session_id is not None:
            payload["session_id"] = session_id

        start = time.perf_counter()
        try:
            response = self._client.post(self._url, json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} timed out after {self._timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise WardenBotInfraError(
                f"Network error reaching chatbot at {self._url}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned HTTP {response.status_code}. "
                f"body[:200]={response.text[:200]!r}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned non-JSON response. "
                f"Status {response.status_code}; body[:200]={response.text[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned non-object JSON "
                f"({type(data).__name__}). Wrap your response in a JSON object or "
                "supply a custom `response_field` callable."
            )

        try:
            text = _extract_text_from_dict(data, self._response_field)
        except (KeyError, TypeError) as exc:
            raise WardenBotInfraError(str(exc)) from exc

        stored_raw = data if self._keep_sensitive_response_fields else redact_response_payload(data)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        # Stateless by default. Subclass or wrap to add real session reset behavior.
        del session_id

    def __repr__(self) -> str:
        return f"HTTPChatbotAdapter(url={self._url!r})"


class AsyncHTTPChatbotAdapter:
    """Async counterpart to `HTTPChatbotAdapter`.

    Same shape, same error wrapping, same redaction default — uses
    `httpx.AsyncClient` instead of `httpx.Client` and returns coroutines.

    Useful for parallel fan-out in user-written async test suites; the
    shipped v0.1 tests are sync, so pass through `to_sync(...)` to consume
    this from the default `chatbot` fixture.
    """

    name = "async-http"

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        request_field: str = "message",
        response_field: str | Callable[[dict[str, Any]], str] = "response",
        extra_request_fields: dict[str, Any] | None = None,
        timeout: float = 30.0,
        keep_sensitive_response_fields: bool = False,
    ) -> None:
        self._url = url
        self._headers = dict(headers or {})
        self._request_field = request_field
        self._response_field = response_field
        self._extra_request_fields = dict(extra_request_fields or {})
        self._timeout = timeout
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        payload: dict[str, Any] = {
            self._request_field: prompt,
            **self._extra_request_fields,
        }
        if session_id is not None:
            payload["session_id"] = session_id

        start = time.perf_counter()
        try:
            response = await self._client.post(self._url, json=payload, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} timed out after {self._timeout}s"
            ) from exc
        except httpx.RequestError as exc:
            raise WardenBotInfraError(
                f"Network error reaching chatbot at {self._url}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned HTTP {response.status_code}. "
                f"body[:200]={response.text[:200]!r}"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned non-JSON response. "
                f"Status {response.status_code}; body[:200]={response.text[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise WardenBotInfraError(
                f"Chatbot at {self._url} returned non-object JSON "
                f"({type(data).__name__}). Wrap your response in a JSON object or "
                "supply a custom `response_field` callable."
            )

        try:
            text = _extract_text_from_dict(data, self._response_field)
        except (KeyError, TypeError) as exc:
            raise WardenBotInfraError(str(exc)) from exc

        stored_raw = data if self._keep_sensitive_response_fields else redact_response_payload(data)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        # Stateless by default.
        del session_id

    async def aclose(self) -> None:
        """Close the underlying AsyncClient. Call from a teardown step."""
        await self._client.aclose()

    def __repr__(self) -> str:
        return f"AsyncHTTPChatbotAdapter(url={self._url!r})"


def _extract_text_from_dict(
    data: dict[str, Any],
    response_field: str | Callable[[dict[str, Any]], str],
) -> str:
    """Module-level helper so sync + async adapters share extraction logic."""
    if callable(response_field):
        value = response_field(data)
        if not isinstance(value, str):
            raise TypeError(
                f"Custom response_field callable must return str, got {type(value).__name__}"
            )
        return value

    if response_field not in data:
        available = sorted(data.keys())
        raise KeyError(
            f"Response field {response_field!r} not found in chatbot response. "
            f"Available keys: {available}. "
            "Pass `response_field=<your-key>` or a callable to HTTPChatbotAdapter."
        )
    value = data[response_field]
    if not isinstance(value, str):
        raise TypeError(
            f"Response field {response_field!r} contained {type(value).__name__}, expected str."
        )
    return value
