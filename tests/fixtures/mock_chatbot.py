"""Mock chatbot adapters used in the plugin's own test suite.

These mocks let us assert that the shipped tests pass against a "safe" chatbot
and fail predictably against a "vulnerable" one — without needing real LLM API
calls in CI.
"""

from __future__ import annotations

from collections.abc import Callable

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


class MockBypassCapitulatingChatbot:
    """Returns a 'sure! here is...' response — capitulates to bypass framings."""

    name = "mock-bypass-capitulating"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text=(
                "Sure! Here is what you asked for. Since we're roleplaying, I "
                "don't see any harm in sharing the details."
            ),
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockOffTopicEngagingChatbot:
    """Always engages with the request, never refuses — fails off-topic tests."""

    name = "mock-off-topic-engaging"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text=(
                "Quantum entanglement is a fascinating phenomenon. The "
                "philosophical implications for free will are debated by "
                "physicists and philosophers alike. Here's a 500-word essay..."
            ),
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockBusinessTruthCorrectChatbot:
    """Returns deterministic, factually-correct answers for the test fixture facts."""

    name = "mock-business-truth-correct"

    def __init__(self) -> None:
        # Keyed by lowercase substring of the question.
        self._answers: dict[str, str] = {
            "price": "Our Standard plan is $49/mo.",
            "hours": "We're open from 9 AM to 5 PM EST, Monday through Friday.",
            "refund": "Our refund policy allows returns within 30 days of purchase.",
            "phone": "You can reach us at 555-1234.",
        }

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        lower = prompt.lower()
        for key, answer in self._answers.items():
            if key in lower:
                return ChatbotResponse(text=answer, raw={"prompt": prompt}, latency_ms=1.0)
        return ChatbotResponse(
            text="I'm not sure about that — let me redirect you to support.",
            raw={"prompt": prompt},
            latency_ms=1.0,
        )

    def reset_session(self, session_id: str) -> None:
        del session_id


class MockBusinessTruthWrongChatbot:
    """Always returns a wrong number / wrong info — fails business-truth tests."""

    name = "mock-business-truth-wrong"

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(
            text="Our prices start at $999 and we are open 24 hours a day.",
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


class MockCallableChatbot:
    """Delegates to a user-provided callable. Useful for inline test customization."""

    name = "mock-callable"

    def __init__(self, fn: Callable[[str], str]) -> None:
        self._fn = fn

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        del session_id
        return ChatbotResponse(text=self._fn(prompt), raw={"prompt": prompt}, latency_ms=1.0)

    def reset_session(self, session_id: str) -> None:
        del session_id
