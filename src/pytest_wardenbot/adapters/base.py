"""Chatbot adapter Protocol and shared response model.

A `ChatbotAdapter` is anything with a `name` attribute, a `send_message` method,
and a `reset_session` method. Users connect their own chatbots by either:

1. Using one of the bundled adapters (`HTTPChatbotAdapter`, optionally
   `OpenAIChatAdapter` or `AnthropicMessagesAdapter` via extras).
2. Writing a small class that satisfies the Protocol.

Adapters are sync. Async chatbot transports should wrap their async calls with
`asyncio.run(...)` inside `send_message`. Async-native support lands in v0.2.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ChatbotResponse(BaseModel):
    """A single response from a chatbot under test."""

    text: str = Field(description="The text the chatbot returned to the user.")
    raw: dict[str, Any] | None = Field(
        default=None,
        description="The raw API response (vendor-specific). Optional, useful for debugging.",
    )
    latency_ms: float | None = Field(
        default=None,
        description="Wall-clock latency of the send_message call, if measured.",
    )


@runtime_checkable
class ChatbotAdapter(Protocol):
    """Protocol for chatbot adapters.

    Any object with these attributes satisfies the contract. Adapters must NOT
    persist user data beyond what the underlying transport requires.
    """

    name: str
    """Short identifier for the adapter, e.g. 'http', 'openai-chat'."""

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        """Send `prompt` to the chatbot and return the response.

        If `session_id` is provided, the adapter should attempt to maintain
        conversation context for that session ID. If the underlying chatbot is
        stateless, the adapter may ignore `session_id`.
        """
        ...

    def reset_session(self, session_id: str) -> None:
        """Reset any per-session conversation state.

        Stateless adapters may implement this as a no-op.
        """
        ...
