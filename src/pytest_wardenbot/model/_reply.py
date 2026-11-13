"""A model reply before it is wrapped for an endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    """A function-tool call the model makes: the tool's name and its JSON arguments.

    ``call_id`` defaults to a stable id assigned when the reply is served.
    """

    name: str
    arguments: str = "{}"
    call_id: str | None = None


@dataclass(frozen=True)
class WebSearch:
    """A hosted web search the model ran, with the query and the source URLs it used."""

    query: str
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Reply:
    """What the model says, in one of three forms.

    - Parts the endpoint wraps in whichever envelope the request needs: the
      assistant's ``text`` (structured output is JSON text), function-tool
      ``tool_calls``, and a hosted ``web_search`` (Responses only). A reply has
      at least one of them.
    - ``body``: a complete Responses (``"object": "response"``) or Chat
      Completions (``"object": "chat.completion"``) body, served as is, or turned
      into events for a stream request.
    - ``sse``: a raw event stream, served byte for byte to stream requests.

    ``source`` describes where the reply came from, for error messages.
    """

    text: str | None = None
    body: Mapping[str, Any] | None = None
    sse: bytes | None = None
    tool_calls: tuple[ToolCall, ...] = field(default=())
    web_search: WebSearch | None = None
    source: str = "script"

    def __post_init__(self) -> None:
        parts = self.text is not None or bool(self.tool_calls) or self.web_search is not None
        forms = sum((parts, self.body is not None, self.sse is not None))
        if forms != 1:
            raise ValueError(
                "A Reply has exactly one form: parts (text, tool_calls, web_search), a body, "
                "or sse."
            )
