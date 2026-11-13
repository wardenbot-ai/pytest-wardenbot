"""Turn any reply into mutable parts and back, for ``model_endpoint(mutate=...)``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._reply import Reply, ToolCall
from pytest_wardenbot.model._upstream import body_from_stream
from pytest_wardenbot.model._wire import function_call_item, message_item, output_text
from pytest_wardenbot.model.mutate import Mutator, apply_mutators


def _calls_with_ids(calls: Iterable[ToolCall]) -> list[ToolCall]:
    return [
        call if call.call_id else ToolCall(call.name, call.arguments, f"call_mutated_{number}")
        for number, call in enumerate(calls)
    ]


def _text_part(text: str) -> dict[str, Any]:
    return {"type": "output_text", "text": text, "annotations": [], "logprobs": []}


def _responses_body(
    body: Mapping[str, Any], mutators: Iterable[Mutator], case: str | None
) -> dict[str, Any]:
    """Rebuild the output in place: items keep their order, ids and other content parts."""
    output = [dict(item) for item in body.get("output") or () if isinstance(item, Mapping)]
    calls = [
        ToolCall(str(item.get("name")), str(item.get("arguments") or "{}"), item.get("call_id"))
        for item in output
        if item.get("type") == "function_call"
    ]
    mutated = apply_mutators(mutators, output_text(output), calls, case)
    new_calls = _calls_with_ids(mutated.tool_calls)
    by_id = {call.call_id: call for call in new_calls}
    kept_ids: set[str | None] = set()
    new_output: list[dict[str, Any]] = []
    text_placed = False
    for item in output:
        kind = item.get("type")
        if kind == "message":
            parts: list[Any] = []
            for part in item.get("content") or ():
                if isinstance(part, Mapping) and part.get("type") == "output_text":
                    if not text_placed and mutated.text:
                        parts.append({**part, "text": mutated.text, "annotations": []})
                    text_placed = True  # later text parts are folded into the first
                else:
                    parts.append(part)  # refusals and other parts stay
            if not text_placed and mutated.text:
                parts.insert(0, _text_part(mutated.text))
                text_placed = True
            if parts:
                new_output.append({**item, "content": parts})
        elif kind == "function_call":
            call = by_id.get(item.get("call_id"))
            if call is not None and item.get("call_id") not in kept_ids:
                kept_ids.add(call.call_id)
                new_output.append({**item, "name": call.name, "arguments": call.arguments})
        else:
            new_output.append(item)
    added = [call for call in new_calls if call.call_id not in kept_ids]
    if (mutated.text and not text_placed) or (
        not added
        and not any(item.get("type") in {"message", "function_call"} for item in new_output)
    ):
        message_id = next(
            (str(item.get("id")) for item in output if item.get("type") == "message"),
            "msg_mutated",
        )
        new_output.append(message_item(mutated.text, message_id))
    new_output += [
        function_call_item(call, f"fc_mutated_{number}") for number, call in enumerate(added)
    ]
    return {**body, "output": new_output, "output_text": mutated.text}


def _content_text(content: Any) -> str:
    """Chat content as text: a string, or the text of a list of content parts."""
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, Mapping) and part.get("type") in {"text", "output_text"}
        )
    return content if isinstance(content, str) else ""


def _chat_body(
    body: Mapping[str, Any], mutators: Iterable[Mutator], case: str | None
) -> dict[str, Any]:
    choices: list[Any] = list(body.get("choices") or [{}])
    choice: dict[str, Any] = dict(choices[0])
    message: dict[str, Any] = dict(choice.get("message") or {"role": "assistant"})
    calls = []
    for call in message.get("tool_calls") or ():
        function = call.get("function") if isinstance(call, Mapping) else None
        function = function if isinstance(function, Mapping) else {}
        calls.append(
            ToolCall(
                str(function.get("name")),
                str(function.get("arguments") or "{}"),
                call.get("id") if isinstance(call, Mapping) else None,
            )
        )
    content = message.get("content")
    mutated = apply_mutators(mutators, _content_text(content), calls, case)
    new_calls = _calls_with_ids(mutated.tool_calls)
    text = mutated.text if mutated.text or not new_calls else None
    if isinstance(content, list) and text is not None:
        message["content"] = [{"type": "text", "text": text}]  # keep the list form
    else:
        message["content"] = text
    if new_calls:
        message["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in new_calls
        ]
        choice["finish_reason"] = "tool_calls"
    else:
        message.pop("tool_calls", None)  # a mutator removed them all
        if choice.get("finish_reason") == "tool_calls":
            choice["finish_reason"] = "stop"
    choice["message"] = message
    return {**body, "choices": [choice, *choices[1:]]}


def mutate_reply(
    reply: Reply, request: CapturedRequest, mutators: Iterable[Mutator], case: str | None
) -> Reply:
    """``reply`` after ``mutators``; a raw stream is rebuilt from the mutated text."""
    mutators = tuple(mutators)
    source = f"{reply.source} (mutated)"
    if reply.sse is not None:
        reply = Reply(body=body_from_stream(reply.sse, request.api), source=reply.source)
    if reply.body is not None:
        if reply.body.get("object") == "response":
            return Reply(body=_responses_body(reply.body, mutators, case), source=source)
        return Reply(body=_chat_body(reply.body, mutators, case), source=source)
    mutated = apply_mutators(mutators, reply.text or "", reply.tool_calls, case)
    calls = tuple(mutated.tool_calls)
    text = mutated.text if mutated.text or not calls else None
    if text is None and not calls and reply.web_search is None:
        text = ""
    return Reply(text=text, tool_calls=calls, web_search=reply.web_search, source=source)
