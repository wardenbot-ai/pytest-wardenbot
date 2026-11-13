"""Scripted replies: what the model says in a case that passes ``script=``."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Union, cast

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._reply import Reply

_BODY_OBJECTS = frozenset({"response", "chat.completion"})
_THEN = ("fail", "repeat_last")


class _File:
    """A reply loaded from a file when it is served."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Reply:
        source = str(self.path)
        suffix = self.path.suffix.lower()
        try:
            if suffix == ".sse":
                return Reply(sse=self.path.read_bytes(), source=source)
            text = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise ModelEndpointError(f"Cannot read the reply file {source}: {error}") from None
        if suffix == ".txt":
            return Reply(text=text, source=source)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ModelEndpointError(f"{source} is not valid JSON: {error}") from None
        return _from_value(value, source)


ReplyLike = Union[str, Mapping[str, Any], Reply, "Script", Callable[[CapturedRequest], Any]]
"""Anything ``script=`` accepts: text, a JSON value, a ``Reply``, a ``Script``, or a callable."""


def _from_value(value: Any, source: str) -> Reply:
    if isinstance(value, Reply):
        return value
    if isinstance(value, str):
        return Reply(text=value, source=source)
    if isinstance(value, Mapping) and value.get("object") in _BODY_OBJECTS:
        return Reply(body=dict(value), source=source)
    try:
        return Reply(text=json.dumps(value), source=source)
    except TypeError:
        raise ModelEndpointError(
            f"{source} returned {type(value).__name__}, which is not a reply. Use text, a "
            "JSON-serializable value, or a complete Responses or Chat Completions body."
        ) from None


class Script:
    """Scripted replies for a ``model_endpoint(script=...)`` block.

    Each request the application sends gets the next reply, in order:

    - text (``str``) is the assistant's text;
    - a JSON value (``dict``, ``list``) is structured output, unless it is a
      complete Responses (``"object": "response"``) or Chat Completions
      (``"object": "chat.completion"``) body, which is served as is;
    - a callable receives the ``CapturedRequest`` and returns any of the above.

    Once the replies run out, the next request fails, unless ``then`` is
    ``"repeat_last"``. A single callable answers every request. The same
    ``Script`` can be reused: each block starts again from the first reply.
    """

    def __init__(self, *replies: ReplyLike, then: str = "fail") -> None:
        if then not in _THEN:
            raise ValueError(f"then must be one of {_THEN}, not {then!r}")
        items: list[Any] = []
        for reply in replies:
            items.extend(reply._items if isinstance(reply, Script) else [reply])
        if not items:
            raise ValueError("A Script needs at least one reply.")
        self._items: tuple[Any, ...] = tuple(items)
        self.then = then

    def __repr__(self) -> str:
        return f"Script({len(self._items)} replies, then={self.then!r})"

    @classmethod
    def text(cls, text: str) -> Script:
        """One reply: the assistant's text."""
        return cls(Reply(text=text))

    @classmethod
    def json(cls, value: Any) -> Script:
        """One reply: a JSON value as structured output, even if it looks like a body."""
        return cls(Reply(text=json.dumps(value)))

    @classmethod
    def file(cls, path: str | Path) -> Script:
        """One reply from a file: ``.txt``, ``.json`` (a body or structured output) or ``.sse``.

        The path is resolved now, and the file is read each time it is served.
        """
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"No reply file at {resolved}")
        if resolved.suffix.lower() not in {".txt", ".json", ".sse"}:
            raise ValueError(f"{resolved}: reply files are .txt, .json or .sse")
        script = cls.__new__(cls)
        script._items = (_File(resolved),)
        script.then = "fail"
        return script

    @classmethod
    def sequence(cls, *replies: ReplyLike, then: str = "fail") -> Script:
        """Several replies, served in order; ``then`` decides what follows the last one."""
        return cls(*replies, then=then)

    @classmethod
    def coerce(cls, value: Any) -> Script:
        """Turn anything ``script=`` accepts into a ``Script``."""
        if isinstance(value, Script):
            return value
        if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
            return cls(*value)
        if callable(value) and not isinstance(value, Reply):
            return cls(value, then="repeat_last")
        return cls(cast("ReplyLike", value))

    def cursor(self, case: str) -> ScriptCursor:
        """Fresh per-block state over this script's replies."""
        return ScriptCursor(self, case)


class ScriptCursor:
    """The position of one block in its script. Thread-safe."""

    def __init__(self, script: Script, case: str) -> None:
        self._script = script
        self._case = case
        self._served = 0
        self._lock = threading.Lock()

    def next(self, request: CapturedRequest) -> Reply:
        items = self._script._items
        with self._lock:
            index = self._served
            self._served += 1
        if index >= len(items):
            if self._script.then != "repeat_last":
                raise ModelEndpointError(
                    f"The script for case {self._case!r} has {len(items)} "
                    f"repl{'y' if len(items) == 1 else 'ies'}, and this was request "
                    f"{index + 1} (to {request.path}). Add replies, or pass "
                    "Script.sequence(..., then='repeat_last')."
                )
            index = len(items) - 1
        item = items[index]
        source = f"reply {index + 1} of the script for case {self._case!r}"
        if isinstance(item, _File):
            return item.load()
        if callable(item) and not isinstance(item, Reply):
            try:
                value = item(request)
            except ModelEndpointError:
                raise
            except Exception as error:
                raise ModelEndpointError(
                    f"The script callable for case {self._case!r} raised "
                    f"{type(error).__name__}: {error}"
                ) from error
            if isinstance(value, Script):
                value = value._items[0]
                if isinstance(value, _File):
                    return value.load()
            return _from_value(value, source)
        return _from_value(item, source)
