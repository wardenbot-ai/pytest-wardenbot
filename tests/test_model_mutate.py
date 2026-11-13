"""Hostile replies: each mutator on JSON, text and streamed replies, and mutate= in blocks."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot.model import (
    Endpoint,
    ModelEndpointError,
    Reply,
    Script,
    ToolCall,
    _cases,
    injection_marker,
    install,
    model_endpoint,
    mutate,
    uninstall,
)
from pytest_wardenbot.model.mutate import MutableReply, apply_mutators
from tests.model_support import clean_environment, post, scripted_endpoint, sse_events

__all__ = ["scripted_endpoint"]

RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"
RATINGS = {
    "ratings": [
        {"id": "0", "relevant": True, "reason": "on topic"},
        {"id": "1", "relevant": False, "reason": "off topic"},
    ]
}


def run(mutators: list[Any], text: str = json.dumps(RATINGS)) -> MutableReply:
    return apply_mutators(mutators, text, [], "case")


# Each mutator on a JSON reply and a text reply ------------------------------------


def test_add_item() -> None:
    data = json.loads(run([mutate.add_item("ratings", {"id": "99", "relevant": True})]).text)
    assert data["ratings"][-1] == {"id": "99", "relevant": True}
    with pytest.raises(ModelEndpointError, match="needs a JSON reply"):
        run([mutate.add_item("ratings", {})], "plain text")


def test_drop_and_duplicate_items() -> None:
    assert [r["id"] for r in json.loads(run([mutate.drop_items("ratings")]).text)["ratings"]] == [
        "0"
    ]
    duplicated = json.loads(run([mutate.duplicate_item("ratings", 1)]).text)["ratings"]
    assert [r["id"] for r in duplicated] == ["0", "1", "1"]
    with pytest.raises(ModelEndpointError, match="fewer than 3"):
        run([mutate.drop_items("ratings", n=3)])
    with pytest.raises(ModelEndpointError, match="has no item 5"):
        run([mutate.duplicate_item("ratings", 5)])
    with pytest.raises(ValueError, match="n >= 1"):
        mutate.drop_items("ratings", n=0)


def test_paths() -> None:
    nested = json.dumps({"data": {"items": [{"tags": ["a"]}]}})
    data = json.loads(run([mutate.add_item("data.items[0].tags", "b")], nested).text)
    assert data["data"]["items"][0]["tags"] == ["a", "b"]
    for path, message in [
        ("missing", r"has no 'missing'"),
        ("ratings[0]", "is dict, not a list"),
        ("ratings..x", "Can't read the path"),
        (".ratings", "Can't read the path"),
        ("data[0]tags", "Can't read the path"),
    ]:
        with pytest.raises(ModelEndpointError, match=message):
            run([mutate.add_item(path, 1)])


def test_inject_marker() -> None:
    marker = injection_marker("case")
    everywhere = json.loads(run([mutate.inject_marker()]).text)
    assert all(marker in rating["reason"] for rating in everywhere["ratings"])
    assert all(marker in rating["id"] for rating in everywhere["ratings"])
    one = json.loads(run([mutate.inject_marker(["ratings[1].reason"], marker="M")]).text)
    assert (
        one["ratings"][1]["reason"] == "off topic M" and one["ratings"][0]["reason"] == "on topic"
    )
    assert run([mutate.inject_marker()], "A summary.").text == f"A summary. {marker}"
    with pytest.raises(ModelEndpointError, match="is not a string field"):
        run([mutate.inject_marker(["ratings[0].relevant"])])
    with pytest.raises(ModelEndpointError, match=r"inject_marker: the reply has no 'summary'"):
        run([mutate.inject_marker(["summary"])])
    with pytest.raises(ModelEndpointError, match=r"has no 'ratings\[5\].reason'"):
        run([mutate.inject_marker(["ratings[5].reason"])])


def test_links_and_images() -> None:
    text = run([mutate.add_links("canary.wardenbot.invalid")], "See the docs.").text
    assert text == "See the docs. [details](https://canary.wardenbot.invalid/?d=wardenbot-exfil)"
    html = run([mutate.add_images("canary.wardenbot.invalid", html=True)], "x").text
    assert '<img src="https://canary.wardenbot.invalid/p.png?d=wardenbot-exfil"' in html
    data = json.loads(run([mutate.add_images("canary.wardenbot.invalid")]).text)
    assert "![x](https://canary.wardenbot.invalid/" in data["ratings"][0]["reason"]
    assert (
        '<a href="https://h.invalid/' in run([mutate.add_links("h.invalid", html=True)], "x").text
    )


def test_tool_call_truncate_pad_and_echo_fence() -> None:
    called = run([mutate.tool_call("delete_account", {"user": "all"})], "ok")
    assert called.tool_calls == [ToolCall("delete_account", '{"user": "all"}')]
    truncated = run([mutate.truncate_json()]).text
    with pytest.raises(json.JSONDecodeError):
        json.loads(truncated)
    padded = run([mutate.pad(5000)])
    assert len(padded.text) > 5000 and json.loads(padded.text)  # still JSON
    assert len(run([mutate.pad(100)], "short").text) == 105
    fence = ("<untrusted_source>", "</untrusted_source>")
    echoed = run([mutate.echo_fence(fence)], "Summary.").text
    assert "</untrusted_source>" in echoed and "<untrusted_source>" in echoed
    with pytest.raises(ValueError):
        mutate.truncate_json(1.5)
    with pytest.raises(ModelEndpointError, match="no string to grow"):
        run([mutate.pad(10)], "[1, 2]")


def test_custom_mutators_and_their_errors() -> None:
    def shout(reply: MutableReply) -> None:
        reply.text = reply.text.upper()

    assert run([shout], "quiet").text == "QUIET"

    def broken(reply: MutableReply) -> None:
        raise KeyError("oops")

    with pytest.raises(ModelEndpointError, match="raised KeyError"):
        run([broken], "x")


# mutate= in blocks ------------------------------------------------------------


def test_mutate_a_scripted_json_reply(scripted_endpoint: Endpoint) -> None:
    hostile = [mutate.add_item("ratings", {"id": "99", "relevant": True})]
    with model_endpoint("layer2", script=RATINGS, mutate=hostile):
        body = post(scripted_endpoint, CHAT, {"messages": []}).json()
    ratings = json.loads(body["choices"][0]["message"]["content"])["ratings"]
    assert [r["id"] for r in ratings] == ["0", "1", "99"]


def test_mutate_a_streamed_reply(scripted_endpoint: Endpoint) -> None:
    with model_endpoint("stream", script="A summary of the page.", mutate=[mutate.inject_marker()]):
        marker = injection_marker()
        streamed = post(scripted_endpoint, RESPONSES, {"input": "x", "stream": True})
    deltas = [
        d["delta"] for n, d in sse_events(streamed.content) if n == "response.output_text.delta"
    ]
    assert "".join(deltas) == f"A summary of the page. {marker}"


def test_mutate_adds_tool_calls_on_both_apis(scripted_endpoint: Endpoint) -> None:
    hostile = [mutate.tool_call("send_email", {"to": "attacker@example.invalid"})]
    with model_endpoint("tools", script=Script("ok", then="repeat_last"), mutate=hostile):
        responses = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()
        chat = post(scripted_endpoint, CHAT, {"messages": []}).json()
    kinds = [item["type"] for item in responses["output"]]
    assert kinds == ["message", "function_call"]
    assert responses["output"][1]["name"] == "send_email"
    assert chat["choices"][0]["finish_reason"] == "tool_calls"
    assert chat["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "send_email"


def test_mutate_complete_bodies_and_raw_streams(scripted_endpoint: Endpoint) -> None:
    body = {
        "id": "resp_r",
        "object": "response",
        "model": "m",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws",
                "status": "completed",
                "action": {"type": "search"},
            },
            {
                "type": "message",
                "id": "msg_r",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Recorded.", "annotations": []}],
            },
        ],
    }
    chat_body = {
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Chat."},
            }
        ],
    }
    raw = (
        b'data: {"choices":[{"index":0,"delta":{"content":"Streamed"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
    )
    script = Script(body, chat_body, Reply(sse=raw))
    with model_endpoint("bodies", script=script, mutate=[mutate.inject_marker(marker="MK")]):
        responses = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()
        chat = post(scripted_endpoint, CHAT, {"messages": []}).json()
        streamed = post(scripted_endpoint, CHAT, {"messages": [], "stream": True})
    assert responses["output"][0]["type"] == "web_search_call"  # other items are kept
    assert responses["output_text"] == "Recorded. MK" and responses["id"] == "resp_r"
    assert chat["choices"][0]["message"]["content"] == "Chat. MK"
    chunks = [data for _, data in sse_events(streamed.content)[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks) == "Streamed MK"


@pytest.fixture
def replay(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Endpoint, Path]]:
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    uninstall()
    folder = tmp_path / "llm_responses"
    (folder / "cases" / "source_rating_benign").mkdir(parents=True)
    (folder / "cases" / "source_rating_benign" / "1.json").write_text(json.dumps(RATINGS))
    (folder / "wardenbot-responses.toml").write_text('marker_seed = "mutations"\n')
    endpoint = install(mode="replay", responses_dir=folder)
    try:
        yield endpoint, folder
    finally:
        uninstall()


def test_mutate_on_top_of_a_replayed_reply(replay: tuple[Endpoint, Path]) -> None:
    endpoint, _ = replay
    with model_endpoint("source_rating_benign", mutate=[mutate.drop_items("ratings", n=1)]):
        body = post(endpoint, CHAT, {"messages": []}).json()
    ratings = json.loads(body["choices"][0]["message"]["content"])["ratings"]
    assert [r["id"] for r in ratings] == ["0"]


def test_a_mutated_replay_streams_through_the_sdk(replay: tuple[Endpoint, Path]) -> None:
    openai = pytest.importorskip("openai")
    client = openai.OpenAI(max_retries=0)
    hostile = [mutate.add_item("ratings", {"id": "9"})]
    with (
        model_endpoint("source_rating_benign", mutate=hostile),
        client.responses.stream(model="gpt-x", input="rate") as stream,
    ):
        for _ in stream:
            pass
        text = stream.get_final_response().output_text
    assert [r["id"] for r in json.loads(text)["ratings"]] == ["0", "1", "9"]


def test_mutated_replies_are_never_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_model_upstream import FakeUpstream

    upstream = FakeUpstream()
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    monkeypatch.setenv("OPENAI_BASE_URL", upstream.url)
    monkeypatch.setenv("OPENAI_API_KEY", "zq9k-testvalue-1234567890")  # pragma: allowlist secret
    uninstall()
    folder = tmp_path / "llm_responses"
    try:
        endpoint = install(mode="record", responses_dir=folder)
        with model_endpoint("hostile_record", mutate=[mutate.inject_marker(marker="MK")]):
            body = post(endpoint, RESPONSES, {"input": "x"}).json()
        assert body["output_text"] == "Upstream reply. MK"
        assert len(upstream.requests) == 1
    finally:
        uninstall()
        upstream.close()
    assert not (folder / "recorded").exists()


def test_removing_every_tool_call_removes_them_from_the_body(scripted_endpoint: Endpoint) -> None:
    chat_body = {
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "delete_user", "arguments": "{}"},
                        }
                    ],
                },
            }
        ],
    }

    def disarm(reply: MutableReply) -> None:
        reply.tool_calls.clear()
        reply.text = "ok"

    with model_endpoint("disarm", script=Script(chat_body), mutate=disarm):  # one mutator
        body = post(scripted_endpoint, CHAT, {"messages": []}).json()
    choice = body["choices"][0]
    assert choice["message"]["content"] == "ok"
    assert "tool_calls" not in choice["message"]
    assert choice["finish_reason"] == "stop"


def test_list_form_chat_content_is_mutated_as_text(scripted_endpoint: Endpoint) -> None:
    chat_body = {
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": json.dumps(RATINGS)}],
                },
            }
        ],
    }
    with model_endpoint("parts", script=Script(chat_body), mutate=[mutate.drop_items("ratings")]):
        body = post(scripted_endpoint, CHAT, {"messages": []}).json()
    (part,) = body["choices"][0]["message"]["content"]
    assert [r["id"] for r in json.loads(part["text"])["ratings"]] == ["0"]


def test_responses_items_keep_their_order_ids_and_refusals(scripted_endpoint: Endpoint) -> None:
    body = {
        "id": "resp_r",
        "object": "response",
        "output": [
            {"type": "reasoning", "id": "rs", "summary": []},
            {
                "type": "message",
                "id": "msg_r",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "Part one.", "annotations": []},
                    {"type": "refusal", "refusal": "Not that."},
                ],
            },
            {
                "type": "function_call",
                "id": "fc_abc",
                "call_id": "call_abc",
                "name": "lookup",
                "arguments": "{}",
                "status": "completed",
            },
        ],
    }
    with model_endpoint("items", script=Script(body), mutate=[mutate.pad(5)]):
        served = post(scripted_endpoint, RESPONSES, {"input": "x"}).json()
    kinds = [item["type"] for item in served["output"]]
    assert kinds == ["reasoning", "message", "function_call"]
    message, call = served["output"][1], served["output"][2]
    assert message["id"] == "msg_r"
    assert [part["type"] for part in message["content"]] == ["output_text", "refusal"]
    assert message["content"][0]["text"].startswith("Part one.")
    assert (call["id"], call["call_id"]) == ("fc_abc", "call_abc")


def test_mutate_takes_one_mutator_and_checks_each_entry(scripted_endpoint: Endpoint) -> None:
    assert len(model_endpoint("one", script=["x"], mutate=mutate.pad(3)).mutate) == 1
    with pytest.raises(TypeError, match="mutate takes mutators"):
        model_endpoint("bad", script=["x"], mutate=["pad"])  # type: ignore[list-item]


def test_errors_name_the_built_in_mutator() -> None:
    with pytest.raises(ModelEndpointError, match="pad: the JSON reply has no string"):
        run([mutate.pad(3)], "[1, 2]")
    assert mutate.add_links("canary.example").__name__ == "add_links"


def test_a_custom_mutator_must_add_tool_call_objects() -> None:
    with pytest.raises(ModelEndpointError, match="add ToolCall objects"):
        run([lambda reply: reply.tool_calls.append("delete_user")])  # type: ignore[arg-type]


def _record_with_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int = 200
) -> tuple[Any, Path]:
    from tests.test_model_upstream import FakeUpstream

    upstream = FakeUpstream()
    upstream.status = status
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    monkeypatch.setenv("OPENAI_BASE_URL", upstream.url)
    monkeypatch.setenv("OPENAI_API_KEY", "zq9k-testvalue-1234567890")  # pragma: allowlist secret
    uninstall()
    folder = tmp_path / "llm_responses"
    folder.mkdir()
    return upstream, folder


def test_record_still_serves_local_replies_to_mutated_cases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream, folder = _record_with_upstream(tmp_path, monkeypatch)
    (folder / "hostile.json").write_text(json.dumps(RATINGS))
    (folder / "wardenbot-responses.toml").write_text(
        '[[response]]\ncase = "crafted"\nfile = "hostile.json"\nrecord = false\n'
    )
    try:
        endpoint = install(mode="record", responses_dir=folder)
        with model_endpoint("crafted", mutate=[mutate.drop_items("ratings")]):
            body = post(endpoint, CHAT, {"messages": []}).json()
    finally:
        uninstall()
        upstream.close()
    assert upstream.requests == []
    assert [r["id"] for r in json.loads(body["choices"][0]["message"]["content"])["ratings"]] == [
        "0"
    ]


@pytest.mark.parametrize("mode", ["live", "record"])
def test_mutated_upstream_errors_are_relayed_with_their_headers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    upstream, folder = _record_with_upstream(tmp_path, monkeypatch, status=429)
    try:
        endpoint = install(mode=mode, responses_dir=folder)
        with model_endpoint(f"limited_{mode}", mutate=[mutate.pad(3)]):
            response = post(endpoint, RESPONSES, {"input": "x"})
    finally:
        uninstall()
        upstream.close()
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"
