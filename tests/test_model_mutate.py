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
