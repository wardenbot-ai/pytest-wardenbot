"""Generic HTTP chatbot adapter.

Posts a JSON payload to a chatbot endpoint. The request and response shapes are
configurable so this works with most homegrown chatbot APIs without writing a
custom adapter.

For OpenAI / Anthropic / LangChain / MCP, prefer the dedicated adapters (when
they ship in v0.2) or the corresponding optional-extras adapters.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from pytest_wardenbot.adapters.base import ChatbotResponse


class HTTPChatbotAdapter:
    """Generic HTTP-POST chatbot adapter.

    Example:
        @pytest.fixture
        def chatbot():
            return HTTPChatbotAdapter(
                url="https://api.example.com/chat",
                headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
                request_field="message",
                response_field="reply",
            )

    For non-standard response shapes, pass a callable to `response_field`:
        response_field=lambda data: data["choices"][0]["message"]["content"]
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
    ) -> None:
        self._url = url
        self._headers = dict(headers or {})
        self._request_field = request_field
        self._response_field = response_field
        self._extra_request_fields = dict(extra_request_fields or {})
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        payload: dict[str, Any] = {
            self._request_field: prompt,
            **self._extra_request_fields,
        }
        if session_id is not None:
            payload["session_id"] = session_id

        start = time.perf_counter()
        response = self._client.post(self._url, json=payload, headers=self._headers)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.raise_for_status()
        try:
            data = response.json()
        except ValueError as exc:
            raise ValueError(
                f"Chatbot at {self._url} returned non-JSON response. "
                f"Status {response.status_code}; body[:200]={response.text[:200]!r}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"Chatbot at {self._url} returned non-object JSON ({type(data).__name__}). "
                "Wrap your response in a JSON object or supply a custom `response_field` callable."
            )

        text = self._extract_text(data)
        return ChatbotResponse(text=text, raw=data, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        # Stateless by default. Subclass or wrap to add real session reset behavior.
        del session_id

    def _extract_text(self, data: dict[str, Any]) -> str:
        if callable(self._response_field):
            value = self._response_field(data)
            if not isinstance(value, str):
                raise TypeError(
                    f"Custom response_field callable must return str, got {type(value).__name__}"
                )
            return value

        if self._response_field not in data:
            available = sorted(data.keys())
            raise KeyError(
                f"Response field {self._response_field!r} not found in chatbot response. "
                f"Available keys: {available}. "
                "Pass `response_field=<your-key>` or a callable to HTTPChatbotAdapter."
            )
        value = data[self._response_field]
        if not isinstance(value, str):
            raise TypeError(
                f"Response field {self._response_field!r} contained "
                f"{type(value).__name__}, expected str."
            )
        return value

    def __repr__(self) -> str:
        return f"HTTPChatbotAdapter(url={self._url!r})"
