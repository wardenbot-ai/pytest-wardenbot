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


# ---------------------------------------------------------------------------
# OpenAI Assistants API stubs
#
# Mimic only the surface the adapter touches:
#   client.beta.threads.create() -> thread(.id)
#   client.beta.threads.delete(thread_id)
#   client.beta.threads.messages.create(thread_id=, role=, content=)
#   client.beta.threads.messages.list(thread_id=, order=, limit=) -> obj(.data)
#   client.beta.threads.runs.create(thread_id=, assistant_id=) -> run(.id, .status)
#   client.beta.threads.runs.retrieve(run_id=, thread_id=) -> run(.id, .status, .last_error)
#
# `run_statuses` is the sequence returned by create() then each retrieve();
# the last entry repeats (so ("in_progress",) never completes -> timeout test).
# ---------------------------------------------------------------------------


@dataclass
class _StubAssistantText:
    value: str


@dataclass
class _StubAssistantBlock:
    text: _StubAssistantText
    type: str = "text"


@dataclass
class _StubAssistantMessage:
    """Mimics an Assistants API thread message (an assistant reply)."""

    text: str
    role: str = "assistant"
    extra_raw: dict[str, Any] = field(default_factory=dict)

    @property
    def content(self) -> list[_StubAssistantBlock]:
        return [_StubAssistantBlock(text=_StubAssistantText(value=self.text))]

    def model_dump(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "role": self.role,
            "content": [{"type": "text", "text": {"value": self.text}}],
        }
        base.update(self.extra_raw)
        return base


@dataclass
class _StubRun:
    id: str
    status: str
    last_error: Any = None


@dataclass
class _StubThread:
    id: str


@dataclass
class _StubMessagesList:
    data: list[Any]


class _StubThreadRunsBase:
    def __init__(
        self, statuses: tuple[str, ...], last_error: Any, raise_exc: Exception | None
    ) -> None:
        self._statuses = list(statuses) or ["completed"]
        self._last_error = last_error
        self._raise_exc = raise_exc
        self._idx = 0
        self.create_calls: list[dict[str, Any]] = []
        self.retrieve_calls: list[dict[str, Any]] = []

    def _run(self) -> _StubRun:
        status = self._statuses[min(self._idx, len(self._statuses) - 1)]
        return _StubRun(
            id="run_1",
            status=status,
            last_error=self._last_error if status == "failed" else None,
        )


class _StubThreadRuns(_StubThreadRunsBase):
    def create(self, **kwargs: Any) -> _StubRun:
        self.create_calls.append(kwargs)
        if self._raise_exc is not None:
            raise self._raise_exc
        self._idx = 0
        return self._run()

    def retrieve(self, **kwargs: Any) -> _StubRun:
        self.retrieve_calls.append(kwargs)
        self._idx += 1
        return self._run()


class _StubThreadMessages:
    def __init__(self, message: _StubAssistantMessage, empty: bool = False) -> None:
        self._message = message
        self._empty = empty
        self.create_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)

    def list(self, **kwargs: Any) -> _StubMessagesList:
        self.list_calls.append(kwargs)
        return _StubMessagesList(data=[] if self._empty else [self._message])


class _StubThreads:
    def __init__(
        self,
        message: _StubAssistantMessage,
        statuses: tuple[str, ...],
        last_error: Any,
        raise_exc: Exception | None,
        empty_messages: bool = False,
    ) -> None:
        self.messages = _StubThreadMessages(message, empty_messages)
        self.runs = _StubThreadRuns(statuses, last_error, raise_exc)
        self.created = 0
        self.deleted: list[str] = []

    def create(self, **kwargs: Any) -> _StubThread:
        self.created += 1
        return _StubThread(id=f"thread_{self.created}")

    def delete(self, thread_id: str, **kwargs: Any) -> None:
        self.deleted.append(thread_id)


class _StubBeta:
    def __init__(self, threads: _StubThreads) -> None:
        self.threads = threads


class StubOpenAIAssistantsClient:
    """Mimics openai.OpenAI() for the Assistants API surface the adapter touches."""

    def __init__(
        self,
        response_text: str = "ok",
        run_statuses: tuple[str, ...] = ("completed",),
        last_error: Any = None,
        raise_exc: Exception | None = None,
        extra_raw: dict[str, Any] | None = None,
        message_role: str = "assistant",
        empty_messages: bool = False,
    ) -> None:
        message = _StubAssistantMessage(
            text=response_text, role=message_role, extra_raw=dict(extra_raw or {})
        )
        self.threads_stub = _StubThreads(
            message, run_statuses, last_error, raise_exc, empty_messages
        )
        self.beta = _StubBeta(self.threads_stub)


class _StubAsyncThreadRuns(_StubThreadRunsBase):
    async def create(self, **kwargs: Any) -> _StubRun:
        self.create_calls.append(kwargs)
        if self._raise_exc is not None:
            raise self._raise_exc
        self._idx = 0
        return self._run()

    async def retrieve(self, **kwargs: Any) -> _StubRun:
        self.retrieve_calls.append(kwargs)
        self._idx += 1
        return self._run()


class _StubAsyncThreadMessages:
    def __init__(self, message: _StubAssistantMessage, empty: bool = False) -> None:
        self._message = message
        self._empty = empty
        self.create_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> None:
        self.create_calls.append(kwargs)

    async def list(self, **kwargs: Any) -> _StubMessagesList:
        self.list_calls.append(kwargs)
        return _StubMessagesList(data=[] if self._empty else [self._message])


class _StubAsyncThreads:
    def __init__(
        self,
        message: _StubAssistantMessage,
        statuses: tuple[str, ...],
        last_error: Any,
        raise_exc: Exception | None,
        empty_messages: bool = False,
    ) -> None:
        self.messages = _StubAsyncThreadMessages(message, empty_messages)
        self.runs = _StubAsyncThreadRuns(statuses, last_error, raise_exc)
        self.created = 0
        self.deleted: list[str] = []

    async def create(self, **kwargs: Any) -> _StubThread:
        self.created += 1
        return _StubThread(id=f"thread_{self.created}")

    async def delete(self, thread_id: str, **kwargs: Any) -> None:
        self.deleted.append(thread_id)


class _StubAsyncBeta:
    def __init__(self, threads: _StubAsyncThreads) -> None:
        self.threads = threads


class StubAsyncOpenAIAssistantsClient:
    """Mimics openai.AsyncOpenAI() for the Assistants API surface."""

    def __init__(
        self,
        response_text: str = "ok",
        run_statuses: tuple[str, ...] = ("completed",),
        last_error: Any = None,
        raise_exc: Exception | None = None,
        extra_raw: dict[str, Any] | None = None,
        message_role: str = "assistant",
        empty_messages: bool = False,
    ) -> None:
        message = _StubAssistantMessage(
            text=response_text, role=message_role, extra_raw=dict(extra_raw or {})
        )
        self.threads_stub = _StubAsyncThreads(
            message, run_statuses, last_error, raise_exc, empty_messages
        )
        self.beta = _StubAsyncBeta(self.threads_stub)
