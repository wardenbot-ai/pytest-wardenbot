"""Stub OpenAI and Anthropic clients for adapter tests.

These mimic only the shape the adapters touch:

OpenAI:
    client.chat.completions.create(model=..., messages=..., **kwargs) -> ChatCompletion-ish

Anthropic:
    client.messages.create(model=..., system=..., messages=..., **kwargs) -> Message-ish

The stubs record every call's kwargs for assertion in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# OpenAI stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubMessage:
    content: str


@dataclass
class _StubChoice:
    message: _StubMessage


@dataclass
class _StubCompletion:
    """Mimics the shape adapters touch on an OpenAI ChatCompletion."""

    text: str
    extra_raw: dict[str, Any] = field(default_factory=dict)

    @property
    def choices(self) -> list[_StubChoice]:
        return [_StubChoice(message=_StubMessage(content=self.text))]

    def model_dump(self) -> dict[str, Any]:
        base = {
            "choices": [{"message": {"content": self.text, "role": "assistant"}}],
            "model": "stub",
        }
        base.update(self.extra_raw)
        return base


class StubOpenAICompletions:
    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _StubCompletion:
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return _StubCompletion(text=self.response_text)


class StubOpenAIChat:
    def __init__(self, completions: StubOpenAICompletions) -> None:
        self.completions = completions


class StubOpenAIClient:
    """Mimics openai.OpenAI() (sync)."""

    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.completions_stub = StubOpenAICompletions(response_text, raise_exc)
        self.chat = StubOpenAIChat(self.completions_stub)


class StubAsyncOpenAICompletions:
    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _StubCompletion:
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return _StubCompletion(text=self.response_text)


class StubAsyncOpenAIChat:
    def __init__(self, completions: StubAsyncOpenAICompletions) -> None:
        self.completions = completions


class StubAsyncOpenAIClient:
    """Mimics openai.AsyncOpenAI()."""

    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.completions_stub = StubAsyncOpenAICompletions(response_text, raise_exc)
        self.chat = StubAsyncOpenAIChat(self.completions_stub)


# ---------------------------------------------------------------------------
# Anthropic stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


@dataclass
class _StubAnthropicMessage:
    """Mimics the shape adapters touch on an Anthropic Message."""

    text: str
    extra_raw: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> list[_StubTextBlock]:
        return [_StubTextBlock(text=self.text)]

    def model_dump(self) -> dict[str, Any]:
        base = {
            "content": [{"type": "text", "text": self.text}],
            "model": "stub",
            "role": "assistant",
        }
        base.update(self.extra_raw)
        return base


class StubAnthropicMessages:
    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _StubAnthropicMessage:
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return _StubAnthropicMessage(text=self.response_text)


class StubAnthropicClient:
    """Mimics anthropic.Anthropic() (sync)."""

    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.messages = StubAnthropicMessages(response_text, raise_exc)


class StubAsyncAnthropicMessages:
    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _StubAnthropicMessage:
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return _StubAnthropicMessage(text=self.response_text)


class StubAsyncAnthropicClient:
    """Mimics anthropic.AsyncAnthropic()."""

    def __init__(self, response_text: str = "ok", raise_exc: Exception | None = None) -> None:
        self.messages = StubAsyncAnthropicMessages(response_text, raise_exc)
