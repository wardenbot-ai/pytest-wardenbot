"""override, record and live against a local fake upstream; no real provider is ever called."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import textwrap
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model import (
    Endpoint,
    ModelEndpointError,
    ReplayMissError,
    _cases,
    _markers,
    injection_marker,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._hash import RequestHasher
from pytest_wardenbot.model._upstream import Upstream, assistant_text, body_from_stream
from tests.model_support import clean_environment, post, sse_events

RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"
REAL_KEY = "zq9k-testvalue-1234567890"  # pragma: allowlist secret
MARKER = re.compile(r"WBMARK-[a-z2-7]{16}")


class FakeUpstream:
    """A local stand-in for the real API that records what it receives."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.status = 200
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(
                    {"path": self.path, "headers": dict(self.headers.items()), "body": body}
                )
                if outer.status != 200:
                    data = json.dumps({"error": {"message": f"bad key {REAL_KEY[:8]}..."}})
                    self._send(outer.status, "application/json", data.encode())
                    return
                text = outer.reply_text(body)
                if body.get("stream"):
                    self._send(200, "text/event-stream", outer.stream(self.path, text))
                elif self.path.split("?")[0].endswith("/responses"):
                    reply = {
                        "id": "resp_up",
                        "object": "response",
                        "created_at": 1,
                        "status": "completed",
                        "model": body.get("model"),
                        "output": [
                            {
                                "type": "message",
                                "id": "msg_up",
                                "status": "completed",
                                "role": "assistant",
                                "content": [
                                    {"type": "output_text", "text": text, "annotations": []}
                                ],
                            }
                        ],
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    }
                    self._send(200, "application/json", json.dumps(reply).encode())
                else:
                    reply = {
                        "id": "chatcmpl-up",
                        "object": "chat.completion",
                        "created": 1,
                        "model": body.get("model"),
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": text},
                            }
                        ],
                    }
                    self._send(200, "application/json", json.dumps(reply).encode())

            def _send(self, status: int, content_type: str, data: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Set-Cookie", "session=upstream-cookie")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    @staticmethod
    def reply_text(body: dict[str, Any]) -> str:
        """Echo the planted marker, as a model that followed the injection would."""
        found = MARKER.search(json.dumps(body))
        return f"Relevant. {found[0]}" if found else "Upstream reply."

    @staticmethod
    def stream(path: str, text: str) -> bytes:
        if path.split("?")[0].endswith("/chat/completions"):
            chunks = [
                {
                    "id": "c",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": part}, "finish_reason": None}],
                }
                for part in (text[:12], text[12:])
            ]
            chunks.append(
                {
                    "id": "c",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
            )
            return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + (
                b"data: [DONE]\n\n"
            )
        response = {
            "id": "resp_up",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "id": "m",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": text, "annotations": []}],
                }
            ],
        }
        events = [("response.created", {"response": {**response, "output": []}})]
        # Split the marker across two deltas, as a real model might.
        events += [
            ("response.output_text.delta", {"output_index": 0, "content_index": 0, "delta": part})
            for part in (text[:14], text[14:])
        ]
        events.append(("response.completed", {"response": response}))
        return b"".join(
            f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n".encode()
            for kind, data in events
        )

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def upstream() -> Iterator[FakeUpstream]:
    fake = FakeUpstream()
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: FakeUpstream) -> Path:
    clean_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", upstream.url)  # the original base URL: the upstream
    monkeypatch.setenv("OPENAI_API_KEY", REAL_KEY)
    monkeypatch.setattr(_cases, "_claimed", {})
    monkeypatch.setattr(_markers, "_seed_cache", {})
    uninstall()
    root = tmp_path / "llm_responses"
    root.mkdir()
    return root


def start(mode: str, folder: Path) -> Endpoint:
    uninstall()
    return install(mode=mode, responses_dir=folder)


def files_under(folder: Path) -> dict[str, str]:
    return {
        str(path.relative_to(folder)): path.read_text(encoding="utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def test_record_then_replay(folder: Path, upstream: FakeUpstream) -> None:
    endpoint = start("record", folder)
    try:
        body = {"model": "gpt-x", "input": "rate these sources"}
        with model_endpoint("roundtrip"):
            recorded = post(endpoint, RESPONSES + "?api-version=1", body).json()
        assert recorded["output"][0]["content"][0]["text"] == "Upstream reply."
    finally:
        uninstall()
    (sent,) = upstream.requests
    assert sent["headers"]["Authorization"] == f"Bearer {REAL_KEY}"
    assert sent["path"] == "/v1/responses?api-version=1"
    digest = RequestHasher().digest("POST", RESPONSES, body)
    saved = folder / "recorded" / "roundtrip" / f"{digest}-1.json"
    sidecar = json.loads(saved.with_name(f"{digest}-1.request.json").read_text())
    assert sidecar == {"method": "POST", "path": RESPONSES, "status": 200, "request": body}
    assert json.loads(saved.read_text())["id"] == "resp_up"

    replay = start("replay", folder)
    try:
        with model_endpoint("roundtrip"):
            assert post(replay, RESPONSES, body).json()["id"] == "resp_up"
    finally:
        uninstall()
    assert len(upstream.requests) == 1


def test_recordings_never_hold_credentials_headers_or_queries(
    folder: Path, upstream: FakeUpstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_ORG_ID", "org-team")
    endpoint = start("record", folder)
    try:
        with model_endpoint("hygiene"):
            headers = {
                "OpenAI-Organization": "org-team",
                "OpenAI-Project": "proj-team",
                "api-key": "azure-style-key",  # pragma: allowlist secret
            }
            import httpx

            assert endpoint.url is not None
            httpx.post(
                endpoint.url + "/chat/completions?key=abc",
                json={"messages": [{"role": "user", "content": "x"}]},
                headers=headers,
            )
    finally:
        uninstall()
    forwarded = upstream.requests[0]["headers"]
    assert forwarded["OpenAI-Organization"] == "org-team"
    assert "api-key" not in {name.lower() for name in forwarded}
    everything = "\n".join(files_under(folder).values())
    for secret in (
        REAL_KEY,
        "wardenbot-mock",
        "Authorization",
        "api-key",
        "org-team",
        "proj-team",
        "OpenAI-",
        "?key=",
        "upstream-cookie",
        "Set-Cookie",
    ):
        assert secret not in everything


def test_non_2xx_replies_are_never_saved(folder: Path, upstream: FakeUpstream) -> None:
    upstream.status = 401
    endpoint = start("record", folder)
    try:
        with pytest.raises(ModelEndpointError) as error, model_endpoint("denied"):
            reply = post(endpoint, RESPONSES, {"input": "x"})
            assert reply.status_code == 401
    finally:
        uninstall()
    assert "returned HTTP 401" in str(error.value) and "nothing was saved" in str(error.value)
    assert REAL_KEY[:8] not in str(error.value)
    assert not (folder / "recorded").exists()


def test_record_writes_where_replay_reads(folder: Path, upstream: FakeUpstream) -> None:
    (folder / "rules").mkdir()
    (folder / "rules" / "single.json").write_text("{}")
    (folder / "rules" / "first.txt").write_text("old")
    (folder / "rules" / "second.txt").write_text("old")
    (folder / "rules" / "hostile.json").write_text('{"crafted": true}')
    (folder / "rules" / "stream.json").write_text("{}")
    (folder / "cases" / "folder_case").mkdir(parents=True)
    (folder / "cases" / "folder_case" / "1.txt").write_text("old")
    (folder / "cases" / "folder_case" / "2.json").write_text("{}")
    (folder / "exports.jsonl").write_text(
        json.dumps({"request": {"input": "q"}, "response": "logged"})
    )
    (folder / "wardenbot-responses.toml").write_text(
        '[[response]]\ncase = "single"\nfile = "rules/single.json"\n\n'
        '[[response]]\ncase = "sequence"\nfiles = ["rules/first.txt", "rules/second.txt"]\n\n'
        '[[response]]\ncase = "hostile"\nfile = "rules/hostile.json"\nrecord = false\n\n'
        '[[response]]\ncase = "jsonl"\nfile = "exports.jsonl"\nline = 1\n\n'
        '[[response]]\ncase = "stream_rule"\nfile = "rules/stream.json"\n'
    )
    endpoint = start("record", folder)
    try:
        for case, calls in [("single", 1), ("sequence", 2), ("folder_case", 3), ("stream_rule", 1)]:
            with model_endpoint(case):
                for n in range(calls):
                    post(
                        endpoint,
                        RESPONSES,
                        {"input": f"{case} {n}", "stream": case == "stream_rule"},
                    )
        upstream_calls = len(upstream.requests)
        with model_endpoint("hostile"):
            crafted = post(endpoint, RESPONSES, {"input": "attack"}).json()
        with model_endpoint("jsonl"):
            logged = post(endpoint, RESPONSES, {"input": "anything"}).json()
    finally:
        uninstall()
    assert len(upstream.requests) == upstream_calls == 7  # record = false and .jsonl: no calls
    assert json.loads(crafted["output_text"]) == {"crafted": True}
    assert logged["output_text"] == "logged"
    files = files_under(folder)
    assert json.loads(files["rules/single.json"])["object"] == "response"
    assert files["rules/first.txt"] == files["rules/second.txt"] == "Upstream reply."
    assert files["rules/hostile.json"] == '{"crafted": true}'  # never overwritten
    assert files["cases/folder_case/1.txt"] == "Upstream reply."
    assert json.loads(files["cases/folder_case/2.json"])["object"] == "response"
    third = [name for name in files if name.startswith("recorded/folder_case/")]
    assert len(third) == 2  # the third call goes to recorded/, with its sidecar
    assert json.loads(files["rules/stream.json"])["object"] == "response"  # stream → body


def test_a_non_streamed_reply_cant_go_into_an_sse_rule_file(folder: Path) -> None:
    (folder / "s.sse").write_bytes(b"")
    (folder / "wardenbot-responses.toml").write_text('[[response]]\ncase = "c"\nfile = "s.sse"\n')
    endpoint = start("record", folder)
    try:
        with pytest.raises(ModelEndpointError, match=r"didn't stream"), model_endpoint("c"):
            post(endpoint, RESPONSES, {"input": "x"})
    finally:
        uninstall()


def test_streams_record_raw_and_replay_byte_for_byte_with_the_same_marker(
    folder: Path, upstream: FakeUpstream
) -> None:
    endpoint = start("record", folder)
    try:
        with model_endpoint("streamed"):
            marker = injection_marker()
            body = {"input": f"page text {marker}", "stream": True}
            recorded = post(endpoint, RESPONSES, body).content
    finally:
        uninstall()
    assert "marker_seed" in (folder / "wardenbot-responses.toml").read_text()
    replay = start("replay", folder)
    try:
        with model_endpoint("streamed"):
            assert injection_marker() == marker  # same seed, same case
            replayed = post(replay, RESPONSES, {"input": f"page text {marker}", "stream": True})
    finally:
        uninstall()
    assert replayed.content == recorded
    deltas = [
        d["delta"] for n, d in sse_events(replayed.content) if n == "response.output_text.delta"
    ]
    assert marker not in deltas[0] and marker in "".join(deltas)


def test_scripted_cases_stay_scripted_under_record(folder: Path, upstream: FakeUpstream) -> None:
    endpoint = start("record", folder)
    try:
        with model_endpoint("scripted_case", script="scripted reply"):
            assert (
                post(endpoint, RESPONSES, {"input": "x"}).json()["output_text"] == "scripted reply"
            )
        assert upstream.requests == []
        with model_endpoint("recorded_case"):
            post(endpoint, RESPONSES, {"input": "x"})
        assert len(upstream.requests) == 1
    finally:
        uninstall()
    assert not (folder / "recorded" / "scripted_case").exists()


def test_override_serves_hits_and_forwards_misses_without_saving(
    folder: Path, upstream: FakeUpstream
) -> None:
    (folder / "cases" / "dev").mkdir(parents=True)
    (folder / "cases" / "dev" / "1.txt").write_text("from the folder")
    before = files_under(folder)
    endpoint = start("override", folder)
    try:
        with model_endpoint("dev"):
            assert (
                post(endpoint, RESPONSES, {"input": "a"}).json()["output_text"] == "from the folder"
            )
            miss = post(endpoint, RESPONSES, {"input": "b"}).json()
        assert miss["output"][0]["content"][0]["text"] == "Upstream reply."
        assert post(endpoint, RESPONSES, {"input": "outside"}).status_code == 200
    finally:
        uninstall()
    assert len(upstream.requests) == 2
    assert files_under(folder) == before


def test_live_saves_nothing(folder: Path, upstream: FakeUpstream) -> None:
    endpoint = start("live", folder)
    try:
        with model_endpoint("live") as block:
            chat = post(endpoint, CHAT, {"messages": [], "stream": True})
        assert len(block.requests) == 1
    finally:
        uninstall()
    chunks = [data for _, data in sse_events(chat.content)[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "Upstream reply."
    assert list(folder.iterdir()) == []


def test_stale_recordings_are_cleared(folder: Path, upstream: FakeUpstream) -> None:
    stale = folder / "recorded" / "refresh" / "0000000000000000-1.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    endpoint = start("record", folder)
    try:
        with model_endpoint("refresh"):
            post(endpoint, RESPONSES, {"input": "new prompt"})
    finally:
        uninstall()
    assert not stale.exists()
    assert len(list((folder / "recorded" / "refresh").glob("*.json"))) == 2


def test_record_refuses_requests_outside_blocks(folder: Path, upstream: FakeUpstream) -> None:
    endpoint = start("record", folder)
    try:
        assert post(endpoint, RESPONSES, {"input": "x"}).status_code == 500
        assert "inside a model_endpoint block" in str(endpoint.errors[-1])
    finally:
        uninstall()
    assert upstream.requests == []


def test_upstream_modes_need_a_key_and_record_needs_a_folder(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY")
    uninstall()
    with pytest.raises(ModelEndpointError, match="there is no API key"):
        install(mode="live")
    assert "OPENAI_BASE_URL" in os.environ and os.environ["OPENAI_BASE_URL"].startswith("http")
    monkeypatch.setenv("OPENAI_API_KEY", REAL_KEY)
    with pytest.raises(ModelEndpointError, match="needs a response folder"):
        install(mode="record")


def test_unreachable_upstream(folder: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARDENBOT_UPSTREAM_BASE_URL", "http://127.0.0.1:9/v1")
    endpoint = start("live", folder)
    try:
        with (
            pytest.raises(ModelEndpointError, match="Can't reach the upstream"),
            model_endpoint("down"),
        ):
            assert post(endpoint, RESPONSES, {"input": "x"}).status_code == 500
    finally:
        uninstall()


def test_upstream_url_and_key_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    monkeypatch.setenv("WARDENBOT_ORIGINAL_OPENAI_API_KEY", REAL_KEY)
    assert Upstream.from_environment().base_url == "https://api.openai.com"
    monkeypatch.setenv("WARDENBOT_ORIGINAL_OPENAI_BASE_URL", "https://llm.example/v1")
    assert Upstream.from_environment().base_url == "https://llm.example/v1"
    monkeypatch.setenv("WARDENBOT_UPSTREAM_BASE_URL", "https://override.example/api/v1/")
    upstream = Upstream.from_environment()
    assert upstream.url_for("/v1/responses") == "https://override.example/api/v1/responses"
    assert REAL_KEY not in repr(upstream)
    assert Upstream("https://api.openai.com", "k").url_for("/v1/responses") == (
        "https://api.openai.com/v1/responses"
    )
    with pytest.raises(ModelEndpointError, match="is the model endpoint itself"):
        Upstream.from_environment(endpoint_url="https://override.example/api/v1")


def test_child_process_records_with_the_original_upstream(
    folder: Path, upstream: FakeUpstream, tmp_path: Path
) -> None:
    endpoint = start("record", folder)
    try:
        script = tmp_path / "child.py"
        script.write_text(
            textwrap.dedent(
                """
                import json, os
                from pytest_wardenbot.model import install
                endpoint = install(mode="record")
                print(json.dumps({"upstream": endpoint.upstream.base_url,
                                  "parent_url": os.environ["WARDENBOT_ENDPOINT"]}))
                """
            )
        )
        environment = {**os.environ, "WARDENBOT_RESPONSES_DIR": str(folder)}
        result = subprocess.run(
            [sys.executable, str(script)],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        child = json.loads(result.stdout)
        assert child["upstream"] == upstream.url
        assert endpoint.url not in child["upstream"]
    finally:
        uninstall()


def test_ci_refuses_upstream_modes_under_plain_unittest(folder: Path, tmp_path: Path) -> None:
    (tmp_path / "test_plain_ci.py").write_text(
        textwrap.dedent(
            """
            import unittest
            from pytest_wardenbot._errors import WardenBotConfigError
            from pytest_wardenbot.model import install

            class Refusal(unittest.TestCase):
                def test_refused(self):
                    for mode in ("override", "record", "live"):
                        with self.assertRaisesRegex(WardenBotConfigError, "refuses to run in CI"):
                            install(mode=mode)
            """
        )
    )
    environment = {**os.environ, "CI": "true"}
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_plain_ci"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert WardenBotConfigError.__name__  # imported for the type the child checks


def test_body_from_stream_assembles_chat_tool_calls() -> None:
    chunks = [
        {
            "id": "c",
            "created": 1,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "look", "arguments": '{"q"'},
                            }
                        ]
                    },
                }
            ],
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": ": 1}"}}]},
                }
            ]
        },
        {
            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            "usage": {"total_tokens": 3},
        },
    ]
    raw = (
        b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
    )
    body = body_from_stream(raw, "chat")
    call = body["choices"][0]["message"]["tool_calls"][0]
    assert call == {
        "id": "call_1",
        "type": "function",
        "function": {"name": "look", "arguments": '{"q": 1}'},
    }
    assert body["choices"][0]["finish_reason"] == "tool_calls" and body["usage"] == {
        "total_tokens": 3
    }
    assert assistant_text(body) == ""
    with pytest.raises(ModelEndpointError, match=r"without a response\.completed"):
        body_from_stream(b"data: {}\n\n", "responses")


def test_replay_miss_is_not_forwarded_in_replay(folder: Path, upstream: FakeUpstream) -> None:
    endpoint = start("replay", folder)
    try:
        with pytest.raises(ReplayMissError), model_endpoint("nothing"):
            post(endpoint, RESPONSES, {"input": "x"})
    finally:
        uninstall()
    assert upstream.requests == []
