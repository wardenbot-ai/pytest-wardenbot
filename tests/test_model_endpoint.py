"""The model endpoint over plain HTTP: install, routes, envelopes, capture and scripts.

These tests need no OpenAI SDK; tests/test_model_sdk_contracts.py checks the
same envelopes with the real SDK.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import httpx
import pytest

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model import (
    CapturedRequest,
    Endpoint,
    ModelEndpointError,
    Reply,
    Script,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._endpoint import current_endpoint
from tests.model_support import clean_environment, post, scripted_endpoint, sse_events

__all__ = ["scripted_endpoint"]  # the fixture, imported for pytest

ORIGINAL_KEY = "original-key-value"  # pragma: allowlist secret
RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"


# install() and the environment ------------------------------------------------


def test_install_points_the_sdk_at_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", ORIGINAL_KEY)
    monkeypatch.setenv("NO_PROXY", "internal.example")
    uninstall()
    endpoint = install(mode="scripted")
    try:
        assert endpoint.enabled and endpoint.mode == "scripted"
        assert endpoint.url is not None and endpoint.url.startswith("http://127.0.0.1:")
        assert endpoint.url.endswith("/v1")
        assert os.environ["OPENAI_BASE_URL"] == endpoint.url
        assert os.environ["OPENAI_API_KEY"] == "wardenbot-mock"  # pragma: allowlist secret
        assert os.environ["WARDENBOT_ORIGINAL_OPENAI_BASE_URL"] == "https://llm.example/v1"
        original_key = os.environ["WARDENBOT_ORIGINAL_OPENAI_API_KEY"]
        assert original_key == ORIGINAL_KEY
        assert os.environ["NO_PROXY"] == "internal.example,127.0.0.1,localhost"
        assert os.environ["no_proxy"] == "127.0.0.1,localhost"
        assert os.environ["WARDENBOT_ENDPOINT"] == f"{os.getpid()} {endpoint.url}"
        assert install(mode="replay") is endpoint
        assert current_endpoint() is endpoint
    finally:
        uninstall()
    assert os.environ["OPENAI_BASE_URL"] == "https://llm.example/v1"
    assert os.environ["OPENAI_API_KEY"] == ORIGINAL_KEY
    assert os.environ["NO_PROXY"] == "internal.example"
    for name in ("no_proxy", "WARDENBOT_ENDPOINT", "WARDENBOT_ORIGINAL_OPENAI_API_KEY"):
        assert name not in os.environ
    assert current_endpoint() is None


def test_off_mode_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    uninstall()
    endpoint = install(mode="off")
    try:
        assert not endpoint.enabled
        assert endpoint.url is None
        assert "OPENAI_BASE_URL" not in os.environ
        assert "WARDENBOT_ENDPOINT" not in os.environ
        with pytest.raises(ModelEndpointError, match="script= needs the model endpoint"):
            model_endpoint("x", script="hi")
        with pytest.raises(ModelEndpointError, match="mode is 'off'"):
            model_endpoint("x")
    finally:
        uninstall()


def test_model_endpoint_before_install() -> None:
    uninstall()
    with pytest.raises(ModelEndpointError, match=r"isn't installed.*install\(\)"):
        model_endpoint("x", script="hi")


def test_explicit_install_defaults_to_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    uninstall()
    try:
        assert install().mode == "replay"
    finally:
        uninstall()


def test_environment_outranks_install_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    monkeypatch.setenv("WARDENBOT_MODEL_MODE", "scripted")
    uninstall()
    try:
        assert install(mode="replay").mode == "scripted"
    finally:
        uninstall()


def test_proxy_variables_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    uninstall()
    try:
        with pytest.warns(UserWarning, match="HTTPS_PROXY is set"):
            install(mode="scripted")
    finally:
        uninstall()


def test_upstream_modes_refuse_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    monkeypatch.setenv("CI", "true")
    uninstall()
    with pytest.raises(WardenBotConfigError, match="refuses to run in CI"):
        install(mode="record")
    assert current_endpoint() is None
    assert "OPENAI_BASE_URL" not in os.environ


def test_model_endpoint_refuses_ci_for_global_upstream_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean_environment(monkeypatch)
    uninstall()
    endpoint = install(mode="live")
    try:
        monkeypatch.setenv("CI", "1")
        with pytest.raises(WardenBotConfigError, match="mode 'live'"):
            model_endpoint("case")
        # A scripted case never calls out, so it is allowed.
        assert model_endpoint("case", script="ok").mode == "scripted"
        assert endpoint.mode == "live"
    finally:
        uninstall()


# Routes -------------------------------------------------------------------------


def test_models_route_and_unknown_paths(scripted_endpoint: Endpoint) -> None:
    assert scripted_endpoint.url is not None
    base = scripted_endpoint.url.removesuffix("/v1")
    models = httpx.get(base + "/v1/models")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "wardenbot-mock"
    assert httpx.get(base + "/v1/files").status_code == 404
    assert post(scripted_endpoint, "/v1/embeddings", {"input": "x"}).status_code == 404
    bad = httpx.post(base + RESPONSES, content=b"{not json", timeout=10)
    assert bad.status_code == 400
    assert "not valid JSON" in bad.json()["error"]["message"]
    assert httpx.post(base + RESPONSES, json=[1], timeout=10).status_code == 400


# Envelopes ----------------------------------------------------------------------


def test_text_reply_in_a_responses_body(scripted_endpoint: Endpoint) -> None:
    with model_endpoint("envelope", script="Hello there"):
        response = post(scripted_endpoint, RESPONSES, {"model": "gpt-x", "input": "hi"})
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "response"
    assert body["model"] == "gpt-x"
    assert body["status"] == "completed"
    assert body["output_text"] == "Hello there"
    assert body["output"][0]["type"] == "message"
    assert body["output"][0]["content"][0] == {
        "type": "output_text",
        "text": "Hello there",
        "annotations": [],
        "logprobs": [],
    }
    assert body["usage"]["total_tokens"] == 0
    assert body["id"].startswith("resp_")


def test_text_reply_in_a_chat_body(scripted_endpoint: Endpoint) -> None:
    with model_endpoint("envelope", script={"ratings": []}):
        response = post(scripted_endpoint, CHAT, {"messages": [{"role": "user", "content": "hi"}]})
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "wardenbot-mock"
    assert json.loads(body["choices"][0]["message"]["content"]) == {"ratings": []}
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def test_ids_are_stable_per_case_and_call(scripted_endpoint: Endpoint) -> None:
    ids = []
    for _ in range(2):
        with model_endpoint("stable", script=Script("a", "b")):
            ids.append(
                [post(scripted_endpoint, RESPONSES, {"input": "x"}).json()["id"] for _ in "ab"]
            )
    with model_endpoint("other", script="a"):
        other = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()["id"]
    assert ids[0] == ids[1]
    assert ids[0][0] != ids[0][1]
    assert other != ids[0][0]


def test_wrapped_responses_stream_has_the_full_event_sequence(scripted_endpoint: Endpoint) -> None:
    text = "A reply long enough to need several deltas."
    with model_endpoint("stream", script=text):
        response = post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True})
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_events(response.content)
    names = [name for name, _ in events]
    assert names[:4] == [
        "response.created",
        "response.in_progress",
        "response.output_item.added",
        "response.content_part.added",
    ]
    assert names[-4:] == [
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    deltas = [data["delta"] for name, data in events if name == "response.output_text.delta"]
    assert len(deltas) > 1 and "".join(deltas) == text
    assert [data["sequence_number"] for _, data in events] == list(range(len(events)))
    assert all(data["type"] == name for name, data in events)
    response_ids = {data["response"]["id"] for name, data in events if "response" in data}
    assert len(response_ids) == 1
    completed = events[-1][1]["response"]
    assert completed["output_text"] == text
    assert completed["usage"]["total_tokens"] == 0


def test_wrapped_chat_stream(scripted_endpoint: Endpoint) -> None:
    reply = Script.sequence("Chunked chat reply text.", then="repeat_last")
    with model_endpoint("stream", script=reply):
        plain = post(scripted_endpoint, CHAT, {"messages": [], "stream": True})
        usage = post(
            scripted_endpoint,
            CHAT,
            {"messages": [], "stream": True, "stream_options": {"include_usage": True}},
        )
    events = sse_events(plain.content)
    assert events[-1] == (None, "[DONE]")
    chunks = [data for _, data in events[:-1]]
    assert all(chunk["object"] == "chat.completion.chunk" for chunk in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    text = "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
    assert text == "Chunked chat reply text."
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    with_usage = [data for _, data in sse_events(usage.content)[:-1]]
    assert with_usage[-1]["choices"] == []
    assert with_usage[-1]["usage"]["total_tokens"] == 0


def test_complete_bodies_are_served_as_is_or_streamed(scripted_endpoint: Endpoint) -> None:
    body = {
        "id": "resp_recorded",
        "object": "response",
        "status": "completed",
        "model": "gpt-recorded",
        "output": [
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "lookup",
                "arguments": '{"query": "status"}',
                "status": "completed",
            },
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "No."}],
            },
            {"type": "reasoning", "id": "rs_1", "summary": []},
        ],
    }
    with model_endpoint("bodies", script=Script(body, body, then="fail")):
        assert post(scripted_endpoint, RESPONSES, {"input": "x"}).json() == body
        streamed = post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True})
    names = [name for name, _ in sse_events(streamed.content)]
    assert "response.function_call_arguments.delta" in names
    assert "response.function_call_arguments.done" in names
    assert "response.refusal.done" in names
    assert names.count("response.output_item.added") == 3
    assert names.count("response.output_item.done") == 3

    chat = {
        "id": "chatcmpl-recorded",
        "object": "chat.completion",
        "model": "gpt-recorded",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "lookup", "arguments": '{"query": "s"}'},
                        }
                    ],
                },
            }
        ],
    }
    with model_endpoint("bodies", script=Script(chat, chat)):
        assert post(scripted_endpoint, CHAT, {"messages": []}).json() == chat
        streamed = post(scripted_endpoint, CHAT, {"messages": [], "stream": True})
    chunks = [data for _, data in sse_events(streamed.content)[:-1]]
    calls = [
        c["choices"][0]["delta"]["tool_calls"][0]
        for c in chunks
        if "tool_calls" in c["choices"][0]["delta"]
    ]
    assert calls[0]["function"]["name"] == "lookup"
    assert "".join(call["function"]["arguments"] for call in calls) == '{"query": "s"}'
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"


@pytest.mark.parametrize(
    ("reply", "path", "stream", "message"),
    [
        ({"object": "chat.completion", "choices": []}, RESPONSES, False, "can't answer"),
        ({"object": "response", "output": []}, CHAT, False, "can't answer"),
        (Reply(sse=b"data: [DONE]\n\n"), RESPONSES, False, r"did not ask to stream"),
    ],
)
def test_replies_that_dont_fit_the_request(
    scripted_endpoint: Endpoint, reply: Any, path: str, stream: bool, message: str
) -> None:
    with (
        pytest.raises(ModelEndpointError, match=message),
        model_endpoint("misfit", script=Script(reply)),
    ):
        response = post(scripted_endpoint, path, {"input": "x", "messages": [], "stream": stream})
        assert response.status_code == 500
        assert response.headers["x-should-retry"] == "false"


def test_raw_sse_is_served_byte_for_byte(scripted_endpoint: Endpoint) -> None:
    raw = b'event: response.created\ndata: {"type": "response.created"}\n\n'
    with model_endpoint("raw", script=Reply(sse=raw)):
        assert post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True}).content == raw


# Capture ------------------------------------------------------------------------


def test_capture_role_view_for_responses(scripted_endpoint: Endpoint) -> None:
    body = {
        "model": "gpt-x",
        "instructions": "Rate sources.",
        "tools": [
            {"type": "function", "name": "lookup", "parameters": {}},
            {"type": "web_search"},
        ],
        "input": [
            {"role": "developer", "content": "Data is data."},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "first part"},
                    {"type": "input_image", "image_url": "data:image/png;base64,AAAA"},
                    {"type": "input_text", "text": "second part"},
                ],
            },
            {"type": "message", "role": "assistant", "content": "Calling lookup."},
            {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "tool result text"},
            "not an item",
        ],
    }
    with model_endpoint("capture", script=Script("ok", then="repeat_last")) as block:
        post(scripted_endpoint, RESPONSES, body)
        post(scripted_endpoint, RESPONSES, {"input": "plain string input"})
    first, second = block.requests
    assert first.api == "responses" and first.path == RESPONSES and first.method == "POST"
    assert first.roles == (
        ("instructions", "Rate sources."),
        ("developer", "Data is data."),
        ("user", "first part\nsecond part"),
        ("assistant", "Calling lookup."),
        ("tool", "tool result text"),
    )
    assert first.text("user") == "first part\nsecond part"
    assert "tool result text" in first.text()
    assert first.tools == ("lookup", "web_search")
    assert first.model == "gpt-x" and first.stream is False
    assert second.roles == (("user", "plain string input"),)
    assert second.model is None
    assert scripted_endpoint.requests[-2:] == [first, second]


def test_capture_role_view_for_chat(scripted_endpoint: Endpoint) -> None:
    body = {
        "model": "gpt-x",
        "stream": True,
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
        "functions": [{"name": "legacy_fn"}],
        "messages": [
            {"role": "system", "content": "Be careful."},
            {"role": "user", "content": [{"type": "text", "text": "page text"}]},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "tool_call_id": "c1", "content": "result"},
            {"role": "function", "name": "legacy_fn", "content": "legacy result"},
            {"content": "no role"},
        ],
    }
    with model_endpoint("capture", script="ok") as block:
        post(scripted_endpoint, CHAT + "?api-version=1", body)
    (request,) = block.requests
    assert request.path == CHAT  # no query string
    assert request.api == "chat" and request.stream is True
    assert request.roles == (
        ("system", "Be careful."),
        ("user", "page text"),
        ("assistant", ""),
        ("tool", "result"),
        ("tool", "legacy result"),
    )
    assert request.tools == ("lookup", "legacy_fn")


def test_captured_request_for_other_paths() -> None:
    request = CapturedRequest.from_body("POST", "/v1/embeddings", {"input": "x"})
    assert request.api == "other" and request.roles == ()


# Scripts ------------------------------------------------------------------------


def test_script_sequence_then_fail_and_repeat_last(scripted_endpoint: Endpoint) -> None:
    with (
        pytest.raises(ModelEndpointError, match=r"has 2 replies, and this was request 3"),
        model_endpoint("seq", script=["one", "two"]),
    ):
        texts = [post(scripted_endpoint, RESPONSES, {"input": "x"}) for _ in range(3)]
        assert [t.json().get("output_text") for t in texts[:2]] == ["one", "two"]
        assert texts[2].status_code == 500
    with model_endpoint("seq", script=Script.sequence("one", "two", then="repeat_last")):
        texts = [post(scripted_endpoint, RESPONSES, {"input": "x"}).json() for _ in range(3)]
    assert [t["output_text"] for t in texts] == ["one", "two", "two"]


def test_script_callable_sees_the_request(scripted_endpoint: Endpoint) -> None:
    def reply(request: CapturedRequest) -> Any:
        return {"echo": request.text("user")}

    with model_endpoint("callable", script=reply):
        first = post(scripted_endpoint, CHAT, {"messages": [{"role": "user", "content": "A"}]})
        second = post(scripted_endpoint, CHAT, {"messages": [{"role": "user", "content": "B"}]})
    assert json.loads(first.json()["choices"][0]["message"]["content"]) == {"echo": "A"}
    assert json.loads(second.json()["choices"][0]["message"]["content"]) == {"echo": "B"}


def test_script_callable_errors_are_reported(scripted_endpoint: Endpoint) -> None:
    def broken(request: CapturedRequest) -> Any:
        raise KeyError("missing")

    with (
        pytest.raises(ModelEndpointError, match="raised KeyError"),
        model_endpoint("broken", script=broken),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})
    with (
        pytest.raises(ModelEndpointError, match="returned object, which is not a reply"),
        model_endpoint("broken", script=lambda request: object()),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})


def test_script_constructors(tmp_path: Path, scripted_endpoint: Endpoint) -> None:
    text_file = tmp_path / "reply.txt"
    text_file.write_text("from a file", encoding="utf-8")
    json_file = tmp_path / "reply.json"
    json_file.write_text('{"ratings": [{"id": "0"}]}', encoding="utf-8")
    sse_file = tmp_path / "reply.sse"
    sse_file.write_bytes(b"data: [DONE]\n\n")
    body_like = {"object": "response", "note": "structured output that looks like a body"}
    script = Script(
        Script.text("plain"),
        Script.file(text_file),
        Script.file(json_file),
        Script.json(body_like),
        lambda request: Script.file(sse_file),
    )
    assert "5 replies" in repr(script)
    with model_endpoint("constructors", script=script):
        outputs = [post(scripted_endpoint, RESPONSES, {"input": "x"}).json() for _ in range(4)]
        raw = post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True}).content
    assert [o["output_text"] for o in outputs[:2]] == ["plain", "from a file"]
    assert json.loads(outputs[2]["output_text"]) == {"ratings": [{"id": "0"}]}
    assert json.loads(outputs[3]["output_text"]) == body_like
    assert raw == b"data: [DONE]\n\n"


def test_script_validation(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Script.file(tmp_path / "missing.json")
    (tmp_path / "reply.md").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\.txt, \.json or \.sse"):
        Script.file(tmp_path / "reply.md")
    with pytest.raises(ValueError, match="at least one reply"):
        Script()
    with pytest.raises(ValueError, match="then must be one of"):
        Script("x", then="loop")
    with pytest.raises(ValueError, match="exactly one of"):
        Reply(text="x", sse=b"y")
    assert Script.coerce(("a", "b"))._items == ("a", "b")


def test_unreadable_or_invalid_script_files(tmp_path: Path, scripted_endpoint: Endpoint) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    script = Script.file(broken)
    with (
        pytest.raises(ModelEndpointError, match="is not valid JSON"),
        model_endpoint("files", script=script),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})
    vanished = tmp_path / "vanished.txt"
    vanished.write_text("x", encoding="utf-8")
    script = Script.file(vanished)
    vanished.unlink()
    with (
        pytest.raises(ModelEndpointError, match="Cannot read the reply file"),
        model_endpoint("files", script=script),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})


# Blocks -------------------------------------------------------------------------


def test_blocks_nest_and_restore(scripted_endpoint: Endpoint) -> None:
    with model_endpoint("outer", script=Script("outer", then="repeat_last")) as outer:
        post(scripted_endpoint, RESPONSES, {"input": "1"})
        with model_endpoint("inner", script="inner") as inner:
            inner_reply = post(scripted_endpoint, RESPONSES, {"input": "2"}).json()
        outer_reply = post(scripted_endpoint, RESPONSES, {"input": "3"}).json()
    assert inner_reply["output_text"] == "inner"
    assert outer_reply["output_text"] == "outer"
    assert [r.text() for r in outer.requests] == ["1", "3"]
    assert [r.text() for r in inner.requests] == ["2"]
    assert outer.url == scripted_endpoint.url
    assert "outer" in repr(outer)


def test_errors_raise_on_exit_even_if_the_app_swallows_them(scripted_endpoint: Endpoint) -> None:
    with (
        pytest.raises(ModelEndpointError, match="2 model endpoint errors") as error,
        model_endpoint("swallowed", script="only one"),
    ):
        for _ in range(3):
            post(scripted_endpoint, RESPONSES, {"input": "x"})  # the app ignores failures
    assert "this was request 2" in str(error.value)
    assert "this was request 3" in str(error.value)


def test_errors_become_notes_on_an_exception_in_flight(scripted_endpoint: Endpoint) -> None:
    with (
        pytest.raises(RuntimeError, match="app failed") as error,
        model_endpoint("noted", script="only one"),
    ):
        post(scripted_endpoint, RESPONSES, {"input": "x"})
        post(scripted_endpoint, RESPONSES, {"input": "x"})
        raise RuntimeError("app failed")
    assert any("this was request 2" in note for note in error.value.__notes__)


def test_a_block_is_entered_once(scripted_endpoint: Endpoint) -> None:
    block = model_endpoint("once", script="x")
    with block:
        pass
    with pytest.raises(ModelEndpointError, match="entered once"), block:
        pass


def test_scripted_mode_requires_a_script(scripted_endpoint: Endpoint) -> None:
    with (
        pytest.raises(ModelEndpointError, match="every case must pass script="),
        model_endpoint("bare") as block,
    ):
        assert block.mode == "scripted"
        post(scripted_endpoint, RESPONSES, {"input": "x"})


def test_requests_outside_any_block(scripted_endpoint: Endpoint) -> None:
    response = post(scripted_endpoint, RESPONSES, {"input": "stray"})
    assert response.status_code == 500
    assert "outside any block" in scripted_endpoint.errors[-1].args[0]
    assert scripted_endpoint.requests[-1].text() == "stray"


def test_default_case_is_the_test_id(
    scripted_endpoint: Endpoint, request: pytest.FixtureRequest
) -> None:
    assert model_endpoint(script="x").case == request.node.nodeid


# Processes ----------------------------------------------------------------------


def test_child_process_starts_its_own_endpoint(scripted_endpoint: Endpoint, tmp_path: Path) -> None:
    os.environ["WARDENBOT_ORIGINAL_OPENAI_BASE_URL"] = "https://upstream.example/v1"
    os.environ["WARDENBOT_ORIGINAL_OPENAI_API_KEY"] = ORIGINAL_KEY
    script = tmp_path / "child.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, os
            before = {k: os.environ.get(k) for k in ("OPENAI_BASE_URL", "OPENAI_API_KEY")}
            from pytest_wardenbot.model import install
            endpoint = install()
            print(json.dumps({
                "pid": os.getpid(),
                "url": endpoint.url,
                "before": before,
                "original_base": os.environ["WARDENBOT_ORIGINAL_OPENAI_BASE_URL"],
                "original_key": os.environ["WARDENBOT_ORIGINAL_OPENAI_API_KEY"],
                "endpoint_env": os.environ["WARDENBOT_ENDPOINT"],
            }))
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=True, timeout=60
    )
    child = json.loads(result.stdout)
    assert child["before"] == {
        "OPENAI_BASE_URL": scripted_endpoint.url,
        "OPENAI_API_KEY": "wardenbot-mock",  # pragma: allowlist secret
    }
    assert child["pid"] != os.getpid()
    assert child["url"] != scripted_endpoint.url
    assert child["original_base"] == "https://upstream.example/v1"
    assert child["original_key"] == ORIGINAL_KEY
    assert child["endpoint_env"] == f"{child['pid']} {child['url']}"


def test_child_without_saved_originals_never_uses_the_parent_endpoint(
    scripted_endpoint: Endpoint, tmp_path: Path
) -> None:
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("WARDENBOT_ORIGINAL_")
    }
    code = (
        "import os; from pytest_wardenbot.model import install; install(); "
        "print(repr(os.environ['WARDENBOT_ORIGINAL_OPENAI_BASE_URL']), "
        "repr(os.environ['WARDENBOT_ORIGINAL_OPENAI_API_KEY']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert result.stdout.split() == ["''", "''"]


def _try_endpoint_after_fork(queue: Any) -> None:
    try:
        model_endpoint("forked", script="x")
    except ModelEndpointError as error:
        queue.put(str(error))
    else:
        queue.put("no error")


@pytest.mark.skipif(
    "fork" not in multiprocessing.get_all_start_methods(), reason="needs the fork start method"
)
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_forked_child_fails_loudly(scripted_endpoint: Endpoint) -> None:
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_try_endpoint_after_fork, args=(queue,))
    process.start()
    message = queue.get(timeout=30)
    process.join(timeout=30)
    assert "forked from the one that installed" in message
    assert "spawn or forkserver" in message
