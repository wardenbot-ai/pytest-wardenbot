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


def _responses_body(
    body: Mapping[str, Any], mutators: Iterable[Mutator], case: str | None
) -> dict[str, Any]:
    output = [item for item in body.get("output") or () if isinstance(item, Mapping)]
    calls = [
        ToolCall(str(item.get("name")), str(item.get("arguments") or "{}"), item.get("call_id"))
        for item in output
        if item.get("type") == "function_call"
    ]
    mutated = apply_mutators(mutators, output_text(output), calls, case)
    message_id = next(
        (str(item.get("id")) for item in output if item.get("type") == "message"), "msg_mutated"
    )
    kept = [item for item in output if item.get("type") not in {"message", "function_call"}]
    new_calls = _calls_with_ids(mutated.tool_calls)
    new_output = [*kept]
    if mutated.text or not new_calls:
        new_output.append(message_item(mutated.text, message_id))
    new_output += [
        function_call_item(call, f"fc_mutated_{number}") for number, call in enumerate(new_calls)
    ]
    return {**body, "output": new_output, "output_text": mutated.text}


def _chat_body(
    body: Mapping[str, Any], mutators: Iterable[Mutator], case: str | None
) -> dict[str, Any]:
    choices: list[Any] = list(body.get("choices") or [{}])
    choice: dict[str, Any] = dict(choices[0])
    message: dict[str, Any] = dict(choice.get("message") or {"role": "assistant"})
    calls = [
        ToolCall(
            str((call.get("function") or {}).get("name")),
            str((call.get("function") or {}).get("arguments") or "{}"),
            call.get("id"),
        )
        for call in message.get("tool_calls") or ()
    ]
    mutated = apply_mutators(mutators, str(message.get("content") or ""), calls, case)
    new_calls = _calls_with_ids(mutated.tool_calls)
    message["content"] = mutated.text if mutated.text or not new_calls else None
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
