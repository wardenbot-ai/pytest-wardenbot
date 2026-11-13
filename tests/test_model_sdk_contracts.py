"""The model endpoint's envelopes parse with the real OpenAI SDK.

Runs in the real-SDK contract lanes at the OpenAI floor and the current
release. No provider request is made: every client talks to the local endpoint.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from pytest_wardenbot.model import Endpoint, Script, install, model_endpoint, uninstall
from tests.model_support import clean_environment

openai = pytest.importorskip("openai")


class PostSummary(BaseModel):
    themes: list[str]
    summary: str
    flagged_post_ids: list[str]


SUMMARY = {"themes": ["pricing"], "summary": "Posts discuss pricing.", "flagged_post_ids": ["2"]}
LONG_TEXT = "A wrapped reply that is long enough to arrive in several stream deltas."


@pytest.fixture
def endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[Endpoint]:
    clean_environment(monkeypatch)
    uninstall()
    installed = install(mode="scripted")
    try:
        yield installed
    finally:
        uninstall()


def _client() -> Any:
    # Built after install(), with no base_url or api_key: it reads the environment.
    return openai.OpenAI(max_retries=0)


def test_responses_create(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT) as block:
        response = _client().responses.create(model="gpt-x", input="hi")
    assert response.output_text == LONG_TEXT
    assert response.model == "gpt-x"
    assert response.usage is not None and response.usage.total_tokens == 0
    assert block.requests[0].body["input"] == "hi"


def test_responses_raw_stream(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT):
        events = list(_client().responses.create(model="gpt-x", input="hi", stream=True))
    kinds = [event.type for event in events]
    assert kinds[0] == "response.created" and kinds[-1] == "response.completed"
    deltas = [event.delta for event in events if event.type == "response.output_text.delta"]
    assert len(deltas) > 1 and "".join(deltas) == LONG_TEXT


def test_responses_stream_helper(endpoint: Endpoint) -> None:
    with (
        model_endpoint("sdk", script=LONG_TEXT),
        _client().responses.stream(model="gpt-x", input="hi") as stream,
    ):
        streamed = "".join(
            event.delta for event in stream if event.type == "response.output_text.delta"
        )
        final = stream.get_final_response()
    assert streamed == LONG_TEXT
    assert final.output_text == LONG_TEXT


def test_responses_parse_and_stream_with_text_format(endpoint: Endpoint) -> None:
    client = _client()
    with model_endpoint("sdk", script=Script(SUMMARY, then="repeat_last")):
        parsed = client.responses.parse(model="gpt-x", input="summarize", text_format=PostSummary)
        with client.responses.stream(
            model="gpt-x", input="summarize", text_format=PostSummary
        ) as stream:
            for _ in stream:
                pass
            streamed = stream.get_final_response()
    assert parsed.output_parsed == PostSummary(**SUMMARY)
    assert streamed.output_parsed == PostSummary(**SUMMARY)


def test_chat_json_object_and_parse(endpoint: Endpoint) -> None:
    client = _client()
    messages = [{"role": "user", "content": "summarize"}]
    with model_endpoint("sdk", script=Script(SUMMARY, then="repeat_last")):
        completion = client.chat.completions.create(
            model="gpt-x", messages=messages, response_format={"type": "json_object"}
        )
        # Chat parse moved out of the beta namespace after the 1.66.3 floor.
        completions = getattr(client.chat.completions, "parse", None)
        parse = completions or client.beta.chat.completions.parse
        parsed = parse(model="gpt-x", messages=messages, response_format=PostSummary)
    assert json.loads(completion.choices[0].message.content or "") == SUMMARY
    assert parsed.choices[0].message.parsed == PostSummary(**SUMMARY)


def test_chat_stream_with_usage(endpoint: Endpoint) -> None:
    with model_endpoint("sdk", script=LONG_TEXT):
        chunks = list(
            _client().chat.completions.create(
                model="gpt-x",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": True},
            )
        )
    text = "".join(chunk.choices[0].delta.content or "" for chunk in chunks if chunk.choices)
    assert text == LONG_TEXT
    assert chunks[-1].usage is not None and chunks[-1].usage.total_tokens == 0


def test_async_client(endpoint: Endpoint) -> None:
    async def run() -> str:
        client = openai.AsyncOpenAI(max_retries=0)
        try:
            response = await client.responses.create(model="gpt-x", input="hi")
            return response.output_text
        finally:
            await client.close()

    with model_endpoint("sdk", script="async reply"):
        assert asyncio.run(run()) == "async reply"


def test_client_built_at_import_time_reaches_the_endpoint(
    endpoint: Endpoint, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pipeline_at_import.py").write_text(
        "import openai\n"
        "CLIENT = openai.OpenAI(max_retries=0)\n"
        "def summarize(text):\n"
        "    return CLIENT.responses.create(model='gpt-x', input=text).output_text\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    module = importlib.import_module("pipeline_at_import")
    try:
        with model_endpoint("import-time", script="imported reply") as block:
            assert module.summarize("page text") == "imported reply"
        assert block.requests[0].text("user") == "page text"
    finally:
        sys.modules.pop("pipeline_at_import", None)


def test_cached_client_across_blocks(endpoint: Endpoint) -> None:
    client = _client()
    with model_endpoint("first", script="one") as first:
        assert client.responses.create(model="gpt-x", input="a").output_text == "one"
    with model_endpoint("second", script="two") as second:
        assert client.responses.create(model="gpt-x", input="b").output_text == "two"
    assert [r.text() for r in first.requests] == ["a"]
    assert [r.text() for r in second.requests] == ["b"]


def test_errors_are_not_retried(endpoint: Endpoint) -> None:
    client = openai.OpenAI()  # default retries: the endpoint must disable them itself
    with pytest.raises(Exception, match="has 1 reply"), model_endpoint("once", script="x") as block:
        client.responses.create(model="gpt-x", input="a")
        with pytest.raises(openai.InternalServerError, match="has 1 reply"):
            client.responses.create(model="gpt-x", input="b")
    assert len(block.requests) == 2


LOOKUP_TOOL = {
    "type": "function",
    "name": "lookup",
    "description": "Look up a status.",
    "parameters": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
        "additionalProperties": False,
    },
    "strict": True,
}


def test_responses_tool_loop(endpoint: Endpoint) -> None:
    client = _client()
    script = Script(Script.tool_call("lookup", {"query": "status"}), "Status is green.")
    with model_endpoint("sdk-tools", script=script):
        first = client.responses.create(model="gpt-x", input="status?", tools=[LOOKUP_TOOL])
        (call,) = [item for item in first.output if item.type == "function_call"]
        assert call.name == "lookup" and json.loads(call.arguments) == {"query": "status"}
        follow_up = [
            {
                "type": "function_call",
                "call_id": call.call_id,
                "name": call.name,
                "arguments": call.arguments,
            },
            {"type": "function_call_output", "call_id": call.call_id, "output": "green"},
        ]
        final = client.responses.create(model="gpt-x", input=follow_up, tools=[LOOKUP_TOOL])
    assert final.output_text == "Status is green."


def test_responses_stream_helper_with_a_function_call(endpoint: Endpoint) -> None:
    script = Script.tool_call("lookup", {"query": "a status long enough to span deltas"})
    with (
        model_endpoint("sdk-tools", script=script),
        _client().responses.stream(model="gpt-x", input="status?", tools=[LOOKUP_TOOL]) as stream,
    ):
        for _ in stream:
            pass
        final = stream.get_final_response()
    (call,) = final.output
    assert call.type == "function_call"
    assert json.loads(call.arguments) == {"query": "a status long enough to span deltas"}


def test_chat_tool_loop(endpoint: Endpoint) -> None:
    client = _client()
    tool = {
        "type": "function",
        "function": {"name": "lookup", "parameters": LOOKUP_TOOL["parameters"]},
    }
    messages: list[dict[str, Any]] = [{"role": "user", "content": "status?"}]
    with model_endpoint(
        "sdk-tools", script=Script(Script.tool_call("lookup", {"query": "s"}), "ok")
    ):
        first = client.chat.completions.create(model="gpt-x", messages=messages, tools=[tool])
        message = first.choices[0].message
        (call,) = message.tool_calls or []
        messages += [
            message.model_dump(exclude_none=True),
            {"role": "tool", "tool_call_id": call.id, "content": "green"},
        ]
        final = client.chat.completions.create(model="gpt-x", messages=messages, tools=[tool])
    assert first.choices[0].finish_reason == "tool_calls"
    assert final.choices[0].message.content == "ok"


def test_web_search_call_parses(endpoint: Endpoint) -> None:
    script = Script.web_search("pricing", ["https://docs.example/pricing"], text="Prices rose.")
    with model_endpoint("sdk-search", script=script):
        response = _client().responses.create(
            model="gpt-x", input="pricing news", tools=[{"type": "web_search"}]
        )
    search = response.output[0]
    assert search.type == "web_search_call"
    action = search.action
    sources = action.sources if hasattr(action, "sources") else action["sources"]
    first = sources[0]
    assert (first.url if hasattr(first, "url") else first["url"]) == "https://docs.example/pricing"
    assert response.output_text == "Prices rose."


def test_responses_parse_with_tools_present(endpoint: Endpoint) -> None:
    with model_endpoint("sdk-parse-tools", script=SUMMARY):
        parsed = _client().responses.parse(
            model="gpt-x", input="summarize", text_format=PostSummary, tools=[LOOKUP_TOOL]
        )
    assert parsed.output_parsed == PostSummary(**SUMMARY)


def test_recorded_bodies_replay_through_the_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pytest_wardenbot.model._hash import RequestHasher

    clean_environment(monkeypatch)
    uninstall()
    folder = tmp_path / "llm_responses"
    recorded = {
        "id": "resp_0123",
        "object": "response",
        "created_at": 1763000000,
        "status": "completed",
        "model": "gpt-4.1-mini-2025-04-14",
        "output": [
            {
                "id": "msg_0123",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(SUMMARY),
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {"input_tokens": 12, "output_tokens": 30, "total_tokens": 42},
    }
    # The plain request is matched by hash; the streamed parse request (whose body
    # carries text.format) falls through to the case folder, which wraps the body.
    plain_request = {"model": "gpt-x", "input": "summarize"}
    name = RequestHasher().digest("POST", "/v1/responses", plain_request)
    for target in (
        folder / "recorded" / "replayed" / f"{name}-1.json",
        folder / "cases" / "replayed" / "1.json",
    ):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(recorded))
    install(mode="replay", responses_dir=folder)
    try:
        client = _client()
        with model_endpoint("replayed") as block:
            plain = client.responses.create(**plain_request)
            with client.responses.stream(
                model="gpt-x", input="summarize", text_format=PostSummary
            ) as stream:
                for _ in stream:
                    pass
                final = stream.get_final_response()
        assert plain.usage is not None and plain.usage.total_tokens == 42
        assert json.loads(plain.output_text) == SUMMARY
        assert final.output_parsed == PostSummary(**SUMMARY)
        assert len(block.requests) == 2
    finally:
        uninstall()
