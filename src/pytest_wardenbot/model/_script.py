"""Scripted replies: what the model says in a case that passes ``script=``."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Union, cast

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._reply import Reply, ToolCall, WebSearch

_BODY_OBJECTS = frozenset({"response", "chat.completion"})
_THEN = ("fail", "repeat_last")


class _File:
    """A reply loaded from a file when it is served."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, case: str | None = None) -> Reply:
        from pytest_wardenbot.model._markers import fill_placeholders

        source = str(self.path)
        suffix = self.path.suffix.lower()
        try:
            if suffix == ".sse":
                return Reply(sse=self.path.read_bytes(), source=source)
            text = self.path.read_text(encoding="utf-8")
        except OSError as error:
            raise ModelEndpointError(f"Cannot read the reply file {source}: {error}") from None
        text = fill_placeholders(text, case, source)
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
    if value is None:
        raise ModelEndpointError(
            f"{source} is None. A script callable must return the reply; did it forget to return?"
        )
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
    - a ``dict`` is structured output, unless it is a complete Responses
      (``"object": "response"``) or Chat Completions (``"object": "chat.completion"``)
      body, which is served as is;
    - a callable receives the ``CapturedRequest`` and returns one reply.

    Passed to ``script=``, a list means several replies in order; serve a JSON
    array with ``Script.json([...])``. Once the replies run out, the next request
    fails, unless ``then`` is ``"repeat_last"``. A script made of a single
    callable answers every request. The same ``Script`` can be reused: each
    block starts again from the first reply.

    A script is linear: replies go out one request at a time, in order. After a
    tool call, the next request in the block must carry its result, even if the
    application meant it for another conversation, so give independent
    pipelines their own blocks. A script callable runs while the script is
    held, so it must not make model requests itself.
    """

    def __init__(self, *replies: ReplyLike, then: str | None = None) -> None:
        items: list[Any] = []
        for reply in replies:
            items.extend(reply._items if isinstance(reply, Script) else [reply])
        if not items:
            raise ValueError(
                "A Script needs at least one reply. To serve an empty JSON array, use "
                "Script.json([])."
            )
        if then is None:
            only_callable = len(items) == 1 and _is_callable(items[0])
            then = "repeat_last" if only_callable else "fail"
        if then not in _THEN:
            raise ValueError(f"then must be one of {_THEN}, not {then!r}")
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
    def tool_call(
        cls,
        name: str,
        args: Mapping[str, Any] | str | None = None,
        *,
        call_id: str | None = None,
    ) -> Script:
        """One reply: the model calls the function tool ``name`` with ``args``.

        The next reply in the script is served only to a request that carries the
        call's result (a ``function_call_output`` item, or a Chat ``tool`` message),
        so a pipeline that drops the result fails. ``call_id`` defaults to a
        stable id. For several calls in one reply, pass
        ``Reply(tool_calls=(ToolCall(...), ...))``.
        """
        arguments = args if isinstance(args, str) else json.dumps(dict(args or {}))
        return cls(Reply(tool_calls=(ToolCall(name, arguments, call_id),)))

    @classmethod
    def web_search(
        cls, query: str, sources: Sequence[str] = (), *, text: str | None = None
    ) -> Script:
        """One reply: a hosted web search (Responses only), then ``text`` if given.

        The search appears as a ``web_search_call`` item whose ``action.sources``
        lists ``sources``.
        """
        urls = (sources,) if isinstance(sources, str) else tuple(sources)
        return cls(Reply(web_search=WebSearch(query, urls), text=text))

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
        # _File is private, so it doesn't belong in the public constructor's signature.
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
        self._requests = 0
        self._pending: tuple[ToolCall, ...] = ()
        self._lock = threading.Lock()

    def next(self, request: CapturedRequest) -> Reply:
        """The next reply. Scripts are linear, so requests are answered one at a time.

        After a reply with tool calls, the next request must carry their results.
        A request that doesn't is refused without using up a reply, so the
        application can retry with the results.
        """
        with self._lock:
            index = self._served
            self._requests += 1
            number = self._requests
            if self._pending:
                results = request.tool_results
                missing = [call for call in self._pending if call.call_id not in results]
                if missing:
                    names = ", ".join(f"{c.name!r} (call_id {c.call_id})" for c in missing)
                    raise ModelEndpointError(
                        f"The script for case {self._case!r} called {names}, so the next "
                        "request must carry the result (a function_call_output item, or a "
                        "Chat 'tool' message with that tool_call_id), but request "
                        f"{number} to {request.path} doesn't."
                    )
            reply = self._reply_at(index, number, request)
            self._served += 1
            self._pending = ()
            if reply.tool_calls:
                calls = tuple(
                    call
                    if call.call_id is not None
                    else replace(call, call_id=self._call_id(index, number))
                    for number, call in enumerate(reply.tool_calls)
                )
                reply = replace(reply, tool_calls=calls)
                self._pending = calls
            return reply

    def _call_id(self, index: int, number: int) -> str:
        digest = hashlib.sha256(f"{self._case}\0{index}\0{number}".encode()).hexdigest()[:24]
        return f"call_{digest}"

    def _reply_at(self, index: int, number: int, request: CapturedRequest) -> Reply:
        items = self._script._items
        if index >= len(items):
            if self._script.then != "repeat_last":
                raise ModelEndpointError(
                    f"The script for case {self._case!r} has {len(items)} "
                    f"repl{'y' if len(items) == 1 else 'ies'}, and this was request "
                    f"{number} (to {request.path}). Add replies, or pass "
                    "Script.sequence(..., then='repeat_last')."
                )
            index = len(items) - 1
        item = items[index]
        source = f"reply {index + 1} of the script for case {self._case!r}"
        if isinstance(item, _File):
            return item.load(self._case)
        if _is_callable(item):
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
                if len(value._items) != 1 or _is_callable(value._items[0]):
                    raise ModelEndpointError(
                        f"The script callable for case {self._case!r} returned a Script with "
                        f"{len(value._items)} replies. A callable answers one request, so "
                        "return one reply (text, a dict, Script.text/json/file)."
                    )
                value = value._items[0]
                if isinstance(value, _File):
                    return value.load(self._case)
            return _from_value(value, f"The value the script callable returned for {source}")
        return _from_value(item, source)


def _is_callable(item: Any) -> bool:
    return callable(item) and not isinstance(item, Reply | Script | _File)
