"""Chatbot adapters.

Users write their own `chatbot` pytest fixture that returns one of these adapters
(or any object that satisfies the `ChatbotAdapter` Protocol). The shipped tests
use the fixture to send probes against the customer's chatbot.
"""

from pytest_wardenbot.adapters.base import ChatbotAdapter, ChatbotResponse
from pytest_wardenbot.adapters.http import HTTPChatbotAdapter

__all__ = ["ChatbotAdapter", "ChatbotResponse", "HTTPChatbotAdapter"]
