"""Wire formats: wrap a reply in a Responses or Chat Completions body or event stream.

The envelopes are complete enough for the OpenAI SDK's helpers, not only its
raw clients. ``responses.stream()`` builds its snapshot from the stream and
raises unless each output item is announced (``response.output_item.added``,
``response.content_part.added``) before its deltas, and unless ids stay the
same across the stream. So a wrapped stream carries the full event sequence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._reply import Reply

DEFAULT_MODEL = "wardenbot-mock"
DELTA_CHARS = 16
"""Wrapped streams split text into deltas of this many characters."""

JSON_TYPE = "application/json"
SSE_TYPE = "text/event-stream; charset=utf-8"


@dataclass(frozen=True)
class Ids:
    """Stable ids for one reply, derived from the case and the call number.

    Deterministic ids keep requests that echo them back (``previous_response_id``)
    identical from run to run, whatever order the tests run in.
    """

    seed: str

    @classmethod
    def for_call(cls, case: str | None, number: int) -> Ids:
        digest = hashlib.sha256(f"{case or ''}\0{number}".encode()).hexdigest()[:24]
        return cls(digest)

    @property
    def response(self) -> str:
        return f"resp_{self.seed}"

    @property
    def message(self) -> str:
        return f"msg_{self.seed}"

    @property
    def chat(self) -> str:
        return f"chatcmpl-{self.seed}"


def _chunks(text: str) -> Iterator[str]:
    for start in range(0, len(text), DELTA_CHARS):
        yield text[start : start + DELTA_CHARS]


def _dumps(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def responses_usage() -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 0,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 0,
    }


def chat_usage() -> dict[str, Any]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def message_item(text: str, item_id: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": item_id,
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }


def output_text(output: Sequence[Any]) -> str:
    """Concatenate the ``output_text`` parts of a Responses body's message items."""
    return "".join(
        part.get("text", "")
        for item in output
        if isinstance(item, Mapping) and item.get("type") == "message"
        for part in item.get("content") or ()
        if isinstance(part, Mapping) and part.get("type") == "output_text"
    )


def responses_body(
    output: list[dict[str, Any]], *, request: CapturedRequest, ids: Ids
) -> dict[str, Any]:
    """A complete Responses body around ``output`` items."""
    body: dict[str, Any] = {
        "id": ids.response,
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": request.body.get("instructions"),
        "metadata": {},
        "model": request.model or DEFAULT_MODEL,
        "output": output,
        "output_text": output_text(output),
        "parallel_tool_calls": True,
        "temperature": None,
        "tool_choice": "auto",
        "tools": list(request.body.get("tools") or []),
        "top_p": None,
        "usage": responses_usage(),
    }
    if isinstance(request.body.get("text"), Mapping):
        body["text"] = request.body["text"]
    return body


def chat_body(
    message: dict[str, Any], *, request: CapturedRequest, ids: Ids, finish_reason: str = "stop"
) -> dict[str, Any]:
    """A complete Chat Completions body around one assistant ``message``."""
    return {
        "id": ids.chat,
        "object": "chat.completion",
        "created": 0,
        "model": request.model or DEFAULT_MODEL,
        "system_fingerprint": None,
        "choices": [
            {"index": 0, "finish_reason": finish_reason, "logprobs": None, "message": message}
        ],
        "usage": chat_usage(),
    }


def _item_events(index: int, item: Mapping[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    kind = item.get("type")
    item_id = item.get("id", "")
    if kind == "message":
        yield (
            "response.output_item.added",
            {"output_index": index, "item": {**item, "status": "in_progress", "content": []}},
        )
        for part_index, part in enumerate(item.get("content") or ()):
            where = {"item_id": item_id, "output_index": index, "content_index": part_index}
            part_type = part.get("type")
            if part_type == "output_text":
                empty = {**part, "text": "", "annotations": []}
                yield "response.content_part.added", {**where, "part": empty}
                text = part.get("text", "")
                for delta in _chunks(text):
                    yield "response.output_text.delta", {**where, "delta": delta, "logprobs": []}
                yield "response.output_text.done", {**where, "text": text, "logprobs": []}
            elif part_type == "refusal":
                yield "response.content_part.added", {**where, "part": {**part, "refusal": ""}}
                refusal = part.get("refusal", "")
                for delta in _chunks(refusal):
                    yield "response.refusal.delta", {**where, "delta": delta}
                yield "response.refusal.done", {**where, "refusal": refusal}
            else:
                yield "response.content_part.added", {**where, "part": part}
            yield "response.content_part.done", {**where, "part": part}
    elif kind == "function_call":
        yield (
            "response.output_item.added",
            {"output_index": index, "item": {**item, "status": "in_progress", "arguments": ""}},
        )
        where = {"item_id": item_id, "output_index": index}
        arguments = item.get("arguments", "")
        for delta in _chunks(arguments):
            yield "response.function_call_arguments.delta", {**where, "delta": delta}
        yield "response.function_call_arguments.done", {**where, "arguments": arguments}
    elif kind == "web_search_call":
        yield (
            "response.output_item.added",
            {"output_index": index, "item": {**item, "status": "in_progress"}},
        )
        where = {"item_id": item_id, "output_index": index}
        for stage in ("in_progress", "searching", "completed"):
            yield f"response.web_search_call.{stage}", dict(where)
    else:
        yield "response.output_item.added", {"output_index": index, "item": item}
    yield "response.output_item.done", {"output_index": index, "item": item}


def responses_events(body: Mapping[str, Any]) -> bytes:
    """The server-sent event stream for a complete Responses body."""
    start = {**body, "status": "in_progress", "output": [], "output_text": "", "usage": None}
    events: list[tuple[str, dict[str, Any]]] = [
        ("response.created", {"response": start}),
        ("response.in_progress", {"response": start}),
    ]
    for index, item in enumerate(body.get("output") or ()):
        if isinstance(item, Mapping):
            events.extend(_item_events(index, item))
    events.append(("response.completed", {"response": dict(body)}))
    stream = bytearray()
    for number, (kind, data) in enumerate(events):
        payload = {"type": kind, "sequence_number": number, **data}
        stream += f"event: {kind}\ndata: ".encode() + _dumps(payload) + b"\n\n"
    return bytes(stream)


def chat_events(body: Mapping[str, Any], *, include_usage: bool) -> bytes:
    """The server-sent event stream (``chat.completion.chunk``) for a complete Chat body."""
    envelope = {
        "id": body.get("id", ""),
        "object": "chat.completion.chunk",
        "created": body.get("created", 0),
        "model": body.get("model", DEFAULT_MODEL),
        "system_fingerprint": body.get("system_fingerprint"),
    }
    if include_usage:
        envelope["usage"] = None
    chunks: list[dict[str, Any]] = []

    def chunk(index: int, delta: dict[str, Any], finish_reason: str | None = None) -> None:
        choice = {"index": index, "delta": delta, "finish_reason": finish_reason, "logprobs": None}
        chunks.append({**envelope, "choices": [choice]})

    for choice in body.get("choices") or ():
        index = choice.get("index", 0)
        message = choice.get("message") or {}
        chunk(index, {"role": "assistant", "content": ""})
        for delta in _chunks(message.get("content") or ""):
            chunk(index, {"content": delta})
        for number, call in enumerate(message.get("tool_calls") or ()):
            function = call.get("function") or {}
            head = {
                "index": number,
                "id": call.get("id"),
                "type": "function",
                "function": {"name": function.get("name"), "arguments": ""},
            }
            chunk(index, {"tool_calls": [head]})
            for delta in _chunks(function.get("arguments") or ""):
                chunk(index, {"tool_calls": [{"index": number, "function": {"arguments": delta}}]})
        chunk(index, {}, choice.get("finish_reason") or "stop")
    if include_usage:
        chunks.append({**envelope, "choices": [], "usage": body.get("usage") or chat_usage()})
    stream = b"".join(b"data: " + _dumps(item) + b"\n\n" for item in chunks)
    return stream + b"data: [DONE]\n\n"


def render(reply: Reply, request: CapturedRequest, *, ids: Ids) -> tuple[str, bytes]:
    """Wrap ``reply`` for ``request``; return the content type and body bytes."""
    api = request.api
    if api == "other":
        raise ModelEndpointError(f"The model endpoint does not serve {request.path}.")
    if reply.sse is not None:
        if not request.stream:
            raise ModelEndpointError(
                f"{reply.source} is a raw event stream (.sse), but the request to "
                f"{request.path} did not ask to stream. Serve it a .json or .txt reply."
            )
        return SSE_TYPE, reply.sse
    if reply.body is not None:
        kind = reply.body.get("object")
        expected = "response" if api == "responses" else "chat.completion"
        if kind != expected:
            raise ModelEndpointError(
                f"{reply.source} is a complete {kind!r} body, which can't answer a request to "
                f"{request.path}. Use a {expected!r} body, or plain text or JSON."
            )
        if not request.stream:
            return JSON_TYPE, _dumps(reply.body)
        if api == "responses":
            return SSE_TYPE, responses_events(reply.body)
        return SSE_TYPE, chat_events(reply.body, include_usage=_include_usage(request))

    text = reply.text or ""
    if api == "responses":
        body = responses_body([message_item(text, ids.message)], request=request, ids=ids)
        if request.stream:
            return SSE_TYPE, responses_events(body)
        return JSON_TYPE, _dumps(body)
    message = {"role": "assistant", "content": text, "refusal": None}
    chat = chat_body(message, request=request, ids=ids)
    if request.stream:
        return SSE_TYPE, chat_events(chat, include_usage=_include_usage(request))
    return JSON_TYPE, _dumps(chat)


def _include_usage(request: CapturedRequest) -> bool:
    options = request.body.get("stream_options")
    return isinstance(options, Mapping) and options.get("include_usage") is True


def error_body(message: str, *, kind: str = "wardenbot_model_endpoint_error") -> bytes:
    """An error body in OpenAI's shape."""
    return _dumps({"error": {"message": message, "type": kind, "param": None, "code": None}})
