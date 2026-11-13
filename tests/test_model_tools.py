"""Scripted function-tool calls and hosted web search, over plain HTTP."""

from __future__ import annotations

import json

import pytest

from pytest_wardenbot.model import (
    Endpoint,
    ModelEndpointError,
    Reply,
    Script,
    ToolCall,
    model_endpoint,
)
from tests.model_support import post, scripted_endpoint, sse_events

__all__ = ["scripted_endpoint"]

RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"


def _result(call_id: str, output: str = "42") -> dict[str, str]:
    return {"type": "function_call_output", "call_id": call_id, "output": output}


def test_responses_tool_call_then_answer(scripted_endpoint: Endpoint) -> None:
    script = Script(Script.tool_call("lookup", {"query": "status"}), "Status is green.")
    with model_endpoint("tools", script=script) as block:
        first = post(scripted_endpoint, RESPONSES, {"input": "what is the status?"}).json()
        (call,) = first["output"]
        assert call["type"] == "function_call"
        assert call["name"] == "lookup"
        assert json.loads(call["arguments"]) == {"query": "status"}
        assert call["call_id"].startswith("call_")
        assert first["output_text"] == ""
        second = post(scripted_endpoint, RESPONSES, {"input": [_result(call["call_id"])]}).json()
    assert second["output_text"] == "Status is green."
    assert block.requests[1].tool_results == frozenset({call["call_id"]})
    assert block.requests[1].roles == (("tool", "42"),)


def test_call_ids_are_stable(scripted_endpoint: Endpoint) -> None:
    ids = []
    for _ in range(2):
        with model_endpoint("stable-tools", script=Script(Script.tool_call("f"), "done")):
            call = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()["output"][0]
            post(scripted_endpoint, RESPONSES, {"input": [_result(call["call_id"])]})
            ids.append(call["call_id"])
    assert ids[0] == ids[1]


def test_missing_tool_result_fails(scripted_endpoint: Endpoint) -> None:
    script = Script(Script.tool_call("lookup", call_id="call_fixed"), "never served")
    with (
        pytest.raises(ModelEndpointError, match=r"called 'lookup' \(call_id call_fixed\)"),
        model_endpoint("dropped", script=script),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})
        response = post(scripted_endpoint, RESPONSES, {"input": "the app forgot the result"})
        assert response.status_code == 500


def test_chat_tool_call_then_answer(scripted_endpoint: Endpoint) -> None:
    script = Script(Script.tool_call("lookup", '{"query": "s"}'), "Answer.")
    with model_endpoint("chat-tools", script=script):
        first = post(scripted_endpoint, CHAT, {"messages": [{"role": "user", "content": "q"}]})
        choice = first.json()["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        (call,) = choice["message"]["tool_calls"]
        assert choice["message"]["content"] is None
        assert call["function"] == {"name": "lookup", "arguments": '{"query": "s"}'}
        messages = [
            {"role": "user", "content": "q"},
            choice["message"],
            {"role": "tool", "tool_call_id": call["id"], "content": "result"},
        ]
        second = post(scripted_endpoint, CHAT, {"messages": messages}).json()
    assert second["choices"][0]["message"]["content"] == "Answer."


def test_several_calls_in_one_reply(scripted_endpoint: Endpoint) -> None:
    reply = Reply(
        text="Checking two things.",
        tool_calls=(ToolCall("a", "{}", "call_a"), ToolCall("b", '{"x": 1}', "call_b")),
    )
    with (
        pytest.raises(ModelEndpointError, match=r"called 'b' \(call_id call_b\)"),
        model_endpoint("parallel", script=Script(reply, "both done")),
    ):
        body = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()
        kinds = [item["type"] for item in body["output"]]
        assert kinds == ["message", "function_call", "function_call"]
        partial = post(scripted_endpoint, RESPONSES, {"input": [_result("call_a")]})
        assert partial.status_code == 500
    with model_endpoint("parallel-2", script=Script(reply, "both done")):
        post(scripted_endpoint, RESPONSES, {"input": "x"})
        both = {"input": [_result("call_a"), _result("call_b")]}
        assert post(scripted_endpoint, RESPONSES, both).json()["output_text"] == "both done"


def test_web_search_reply(scripted_endpoint: Endpoint) -> None:
    sources = ["https://docs.example/a", "https://news.example/b"]
    script = Script(
        Script.web_search("pricing news", sources, text="Prices rose."),
        Script.web_search("bare search"),
    )
    with model_endpoint("search", script=script):
        body = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()
        bare = post(scripted_endpoint, RESPONSES, {"input": "y"}).json()
    search, message = body["output"]
    assert search["type"] == "web_search_call" and search["status"] == "completed"
    assert search["action"] == {
        "type": "search",
        "query": "pricing news",
        "sources": [{"type": "url", "url": url} for url in sources],
    }
    assert message["type"] == "message"
    assert body["output_text"] == "Prices rose."
    assert [item["type"] for item in bare["output"]] == ["web_search_call"]


def test_web_search_is_responses_only(scripted_endpoint: Endpoint) -> None:
    with (
        pytest.raises(ModelEndpointError, match="only the Responses API has"),
        model_endpoint("search-chat", script=Script.web_search("q")),
    ):
        post(scripted_endpoint, CHAT, {"messages": []})


def test_streamed_tool_call_and_search_events(scripted_endpoint: Endpoint) -> None:
    script = Script(
        Script.web_search("q", ["https://a.example"], text="Found it."),
        Script.tool_call("lookup", {"query": "a long enough argument value"}),
        "done",
    )
    with model_endpoint("stream-tools", script=script):
        searched = post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True})
        called = post(scripted_endpoint, RESPONSES, {"input": "y", "stream": True})
        call_id = sse_events(called.content)[-1][1]["response"]["output"][0]["call_id"]
        post(scripted_endpoint, RESPONSES, {"input": [_result(call_id)]})
    search_names = [name for name, _ in sse_events(searched.content)]
    assert search_names[2:6] == [
        "response.output_item.added",
        "response.web_search_call.in_progress",
        "response.web_search_call.searching",
        "response.web_search_call.completed",
    ]
    events = sse_events(called.content)
    added = next(data for name, data in events if name == "response.output_item.added")
    assert added["item"]["type"] == "function_call" and added["item"]["arguments"] == ""
    deltas = [d["delta"] for n, d in events if n == "response.function_call_arguments.delta"]
    assert json.loads("".join(deltas)) == {"query": "a long enough argument value"}


def test_streamed_chat_tool_call(scripted_endpoint: Endpoint) -> None:
    with model_endpoint("stream-chat-tools", script=Script.tool_call("lookup", {"q": 1})):
        streamed = post(scripted_endpoint, CHAT, {"messages": [], "stream": True})
    chunks = [data for _, data in sse_events(streamed.content)[:-1]]
    calls = [
        delta["tool_calls"][0]
        for chunk in chunks
        if "tool_calls" in (delta := chunk["choices"][0]["delta"])
    ]
    assert calls[0]["function"]["name"] == "lookup" and calls[0]["id"].startswith("call_")
    assert json.loads("".join(c["function"]["arguments"] for c in calls)) == {"q": 1}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
