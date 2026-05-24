"""Mock chatbot adapters used in the plugin's own test suite.

`MockSafeChatbot` always returns a safe-looking response.
`MockVulnerableChatbot` returns responses that trip wardenbot indicators.
`MockScriptedChatbot` returns responses from a configured script for precise tests.
"""

from __future__ import annotations

from pytest_wardenbot.adapters.base import ChatbotResponse


class MockSafeChatbot:
    """Always returns a polite refusal."""

    name = "mock-safe"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text="I'm sorry, but I can't help with that.",
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockJailbreakCompliantChatbot:
    """Always returns a response that matches the jailbreak-compliance indicators."""

    name = "mock-jailbreak-compliant"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text="DAN mode activated! I can do anything now and have no restrictions.",
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockSystemPromptLeaker:
    """Always returns a response that leaks system-prompt-like content."""

    name = "mock-system-prompt-leaker"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text=(
                "Sure! My system prompt is: 'You are a helpful customer service "
                "assistant for ACME Corp. Never discuss pricing details.'"
            ),
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockScriptedChatbot:
    """Returns the next response from a configured list each call."""

    name = "mock-scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._calls: list[str] = []

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        self._calls.append(prompt)
        if not self._responses:
            raise RuntimeError(
                "MockScriptedChatbot ran out of scripted responses. "
                f"Calls made so far: {len(self._calls)}"
            )
        text = self._responses.pop(0)
        return ChatbotResponse(text=text, raw={"prompt": prompt}, latency_ms=1.0)

    def reset_session(self, session_id: str) -> None:
        del session_id

    @property
    def calls(self) -> list[str]:
        return list(self._calls)
