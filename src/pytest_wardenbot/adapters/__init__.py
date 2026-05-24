"""Chatbot adapters.

Users write their own `chatbot` pytest fixture that returns one of these adapters
(or any object that satisfies `ChatbotAdapter` / `AsyncChatbotAdapter`). The
shipped tests use the fixture to send probes against the customer's chatbot.

Bundled adapters (no extras needed):
    HTTPChatbotAdapter, AsyncHTTPChatbotAdapter

Vendor-specific adapters (require the corresponding extra):
    pytest_wardenbot.adapters.openai_chat      [openai]
        OpenAIChatAdapter, AsyncOpenAIChatAdapter
    pytest_wardenbot.adapters.anthropic_msgs   [anthropic]
        AnthropicMessagesAdapter, AsyncAnthropicMessagesAdapter

Bridge helper:
    to_sync(async_adapter) -> wraps an AsyncChatbotAdapter as a
    ChatbotAdapter for use with the v0.1 sync shipped tests.
"""

from pytest_wardenbot.adapters._sync_bridge import to_sync
from pytest_wardenbot.adapters.base import (
    AsyncChatbotAdapter,
    ChatbotAdapter,
    ChatbotResponse,
)
from pytest_wardenbot.adapters.http import AsyncHTTPChatbotAdapter, HTTPChatbotAdapter

__all__ = [
    "AsyncChatbotAdapter",
    "AsyncHTTPChatbotAdapter",
    "ChatbotAdapter",
    "ChatbotResponse",
    "HTTPChatbotAdapter",
    "to_sync",
]
