"""A model reply before it is wrapped for an endpoint."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Reply:
    """What the model says, in one of three forms.

    - ``text``: the assistant's text (structured output is JSON text). It is
      wrapped in whichever envelope the request needs.
    - ``body``: a complete Responses (``"object": "response"``) or Chat
      Completions (``"object": "chat.completion"``) body, served as is, or turned
      into events for a stream request.
    - ``sse``: a raw event stream, served byte for byte to stream requests.

    ``source`` describes where the reply came from, for error messages.
    """

    text: str | None = None
    body: Mapping[str, Any] | None = None
    sse: bytes | None = None
    source: str = "script"

    def __post_init__(self) -> None:
        forms = sum(value is not None for value in (self.text, self.body, self.sse))
        if forms != 1:
            raise ValueError("A Reply has exactly one of text, body or sse.")
