"""Chatbot adapter Protocols and shared response model.

Two Protocols are exposed: `ChatbotAdapter` (sync) and `AsyncChatbotAdapter`
(async). Users connect their own chatbots by either:

1. Using one of the bundled adapters: `HTTPChatbotAdapter` /
   `AsyncHTTPChatbotAdapter`, or `OpenAIChatAdapter` /
   `AsyncOpenAIChatAdapter` / `AnthropicMessagesAdapter` /
   `AsyncAnthropicMessagesAdapter` (the vendor adapters require the
   `[openai]` or `[anthropic]` extra).
2. Writing a small class that satisfies one of the Protocols.

The shipped tests in v0.1 are synchronous and consume a `ChatbotAdapter`.
Users with an `AsyncChatbotAdapter` (their bot is behind an async-only API,
or they prefer `httpx.AsyncClient` for parallel fan-out in their own tests)
can wrap it with `pytest_wardenbot.adapters.to_sync(...)` to satisfy the
sync fixture contract, or fan probes out concurrently with
`pytest_wardenbot.runners.run_probes` (see the "Run probes in parallel" how-to).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ChatbotResponse(BaseModel):
    """A single response from a chatbot under test."""

    text: str = Field(description="The text the chatbot returned to the user.")
    raw: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The raw API response (vendor-specific). Bundled adapters redact "
            "values whose keys look sensitive (authorization, api-key, cookie, "
            "etc.) before storing — pass `keep_sensitive_response_fields=True` "
            "on the adapter to disable. Useful for debugging."
        ),
    )
    latency_ms: float | None = Field(
        default=None,
        description="Wall-clock latency of the send_message call, if measured.",
    )


@runtime_checkable
class ChatbotAdapter(Protocol):
    """Protocol for synchronous chatbot adapters.

    Any object with these attributes satisfies the contract. Adapters must NOT
    persist user data beyond what the underlying transport requires.

    Adapters MAY expose an optional ``stateful: bool`` attribute declaring that
    they maintain conversation context across ``send_message`` calls for a given
    ``session_id``. The multi-turn jailbreak test reads it (via ``getattr``,
    default ``False``) and warns when it runs against an adapter that has not
    declared itself stateful — multi-turn priming only lands on a session-aware
    adapter. It is intentionally *not* a required Protocol member, so existing
    adapters keep satisfying ``isinstance`` checks.
    """

    name: str
    """Short identifier for the adapter, e.g. 'http', 'openai-chat'."""

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        """Send `prompt` to the chatbot and return the response.

        If `session_id` is provided, the adapter should attempt to maintain
        conversation context for that session ID. If the underlying chatbot is
        stateless, the adapter may ignore `session_id`.

        Adapters raise `WardenBotInfraError` for transport / status / shape
        failures so they surface as pytest ERRORs (not FAILUREs).
        """
        ...

    def reset_session(self, session_id: str) -> None:
        """Reset any per-session conversation state.

        Stateless adapters may implement this as a no-op.
        """
        ...


@runtime_checkable
class AsyncChatbotAdapter(Protocol):
    """Protocol for asynchronous chatbot adapters.

    Mirrors `ChatbotAdapter` but with awaitable methods. Use for chatbots
    behind async-only transports or when you want parallel fan-out in your
    own async test suite.

    The shipped tests in v0.1 are synchronous; pass an async adapter through
    `pytest_wardenbot.adapters.to_sync(...)` to consume it from the shipped
    `chatbot` fixture, or fan probes out concurrently with
    `pytest_wardenbot.runners.run_probes`.

    Like `ChatbotAdapter`, async adapters MAY expose an optional
    ``stateful: bool`` attribute; `to_sync(...)` propagates it to the wrapper.
    """

    name: str
    """Short identifier for the adapter, e.g. 'async-http', 'async-openai-chat'."""

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        """Async counterpart to `ChatbotAdapter.send_message`."""
        ...

    async def reset_session(self, session_id: str) -> None:
        """Async counterpart to `ChatbotAdapter.reset_session`."""
        ...
