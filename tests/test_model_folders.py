"""Response folders in replay mode: formats, hashing, lookup order and miss reports."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot.model import (
    Endpoint,
    ModelEndpointError,
    ReplayMissError,
    _cases,
    injection_marker,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._cases import case_dirname
from pytest_wardenbot.model._hash import RequestHasher, builtin_normalize
from tests.model_support import clean_environment, post, sse_events

RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"
HERE = Path(__file__).resolve().parent

RESPONSE_BODY = {
    "id": "resp_recorded",
    "object": "response",
    "status": "completed",
    "model": "gpt-recorded",
    "output": [
        {
            "type": "message",
            "id": "msg_recorded",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": "Recorded reply.", "annotations": []}],
        }
    ],
    "output_text": "Recorded reply.",
}
CHAT_BODY = {
    "id": "chatcmpl-recorded",
    "object": "chat.completion",
    "model": "gpt-recorded",
    "choices": [
        {
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Recorded chat reply."},
        }
    ],
}


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    uninstall()
    root = tmp_path / "llm_responses"
    root.mkdir()
    (root / "wardenbot-responses.toml").write_text('marker_seed = "folder-tests"\n')
    return root


@pytest.fixture
def replay(folder: Path) -> Iterator[Endpoint]:
    endpoint = install(mode="replay", responses_dir=folder)
    try:
        yield endpoint
    finally:
        uninstall()


def digest(path: str, body: dict[str, Any], hasher: RequestHasher | None = None) -> str:
    return (hasher or RequestHasher()).digest("POST", path, body)


def write(path: Path, content: str | bytes | dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        content = json.dumps(content)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def record(
    folder: Path, case: str, path: str, body: dict[str, Any], reply: Any, n: int = 1
) -> None:
    """Write a recorded reply and its request sidecar, as record mode will."""
    name = f"{digest(path, body)}-{n}"
    target = folder / "recorded" / case_dirname(case)
    suffix = ".sse" if isinstance(reply, bytes) else ".json"
    write(target / f"{name}{suffix}", reply)
    write(
        target / f"{name}.request.json",
        {"method": "POST", "path": path, "status": 200, "request": body},
    )


# Formats ------------------------------------------------------------------------


def test_recorded_bodies_on_each_endpoint(folder: Path, replay: Endpoint) -> None:
    responses_request = {"model": "gpt-x", "input": "rate these"}
    chat_request = {"model": "gpt-x", "messages": [{"role": "user", "content": "rate these"}]}
    record(folder, "formats", RESPONSES, responses_request, RESPONSE_BODY)
    record(folder, "formats", RESPONSES, {**responses_request, "stream": True}, RESPONSE_BODY)
    record(folder, "formats", CHAT, chat_request, CHAT_BODY)
    record(folder, "formats", CHAT, {**chat_request, "stream": True}, CHAT_BODY)
    with model_endpoint("formats"):
        assert post(replay, RESPONSES, responses_request).json() == RESPONSE_BODY
        streamed = post(replay, RESPONSES, {**responses_request, "stream": True})
        assert post(replay, CHAT, chat_request).json() == CHAT_BODY
        chat_stream = post(replay, CHAT, {**chat_request, "stream": True})
    events = sse_events(streamed.content)
    assert events[-1][1]["response"]["output_text"] == "Recorded reply."
    deltas = "".join(d["delta"] for n, d in events if n == "response.output_text.delta")
    assert deltas == "Recorded reply."
    chunks = [data for _, data in sse_events(chat_stream.content)[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert text == "Recorded chat reply."


def test_hand_written_text_json_and_sse(folder: Path, replay: Endpoint) -> None:
    case = folder / "cases" / "hand_written"
    write(case / "1.txt", "Plain text reply.")
    write(case / "2.json", {"ratings": [{"id": "0", "relevant": True}]})
    write(case / "3.txt", "Text for chat.")
    write(case / "4.json", {"flagged": []})
    raw = b'event: response.created\ndata: {"type":"response.created"}\n\n'
    write(case / "5.sse", raw)
    with model_endpoint("hand_written"):
        assert post(replay, RESPONSES, {"input": "a"}).json()["output_text"] == "Plain text reply."
        structured = post(replay, RESPONSES, {"input": "b"}).json()["output_text"]
        assert json.loads(structured) == {"ratings": [{"id": "0", "relevant": True}]}
        chat = post(replay, CHAT, {"messages": []}).json()
        assert chat["choices"][0]["message"]["content"] == "Text for chat."
        chat_json = post(replay, CHAT, {"messages": []}).json()
        assert json.loads(chat_json["choices"][0]["message"]["content"]) == {"flagged": []}
        assert post(replay, RESPONSES, {"input": "e", "stream": True}).content == raw


def test_jsonl_exports_matched_by_hash(folder: Path, replay: Endpoint) -> None:
    scoped_request = {"messages": [{"role": "user", "content": "scoped"}]}
    shared_request = {"input": "shared"}
    lines = [
        {"request": scoped_request, "response": "Scoped reply.", "case": "exports"},
        {"request": scoped_request, "response": "Wrong case.", "case": "another"},
        {
            "request": shared_request,
            "response": RESPONSE_BODY,
            "headers": {"Authorization": "Bearer never-served"},  # pragma: allowlist secret
        },
        {"request": {"input": "x"}, "path": "/v1/responses", "response": {"k": 1}},
    ]
    write(folder / "exports" / "app.jsonl", "\n".join(json.dumps(line) for line in lines) + "\n")
    with model_endpoint("exports"):
        chat = post(replay, CHAT, scoped_request).json()
        assert chat["choices"][0]["message"]["content"] == "Scoped reply."
        assert post(replay, RESPONSES, shared_request).json() == RESPONSE_BODY
        assert json.loads(post(replay, RESPONSES, {"input": "x"}).json()["output_text"]) == {"k": 1}
    with pytest.raises(ReplayMissError), model_endpoint("unrelated"):
        # Scoped to another case, so not served here, and not shared either.
        post(replay, CHAT, {"messages": [{"role": "user", "content": "no match"}]})


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("{not json", "is not valid JSON"),
        ('{"response": "x"}', 'must be an object with a "request"'),
        ('{"request": {"input": "x"}}', 'has no "response"'),
        ('{"request": {"other": 1}, "response": "x"}', 'add a "path"'),
    ],
)
def test_invalid_jsonl_lines(folder: Path, replay: Endpoint, line: str, message: str) -> None:
    write(folder / "bad.jsonl", line + "\n")
    with pytest.raises(ModelEndpointError, match=message), model_endpoint("bad"):
        post(replay, RESPONSES, {"input": "x"})


# Hashing ------------------------------------------------------------------------


def test_hash_ignores_key_order_but_not_stream() -> None:
    first = {"model": "m", "input": [{"role": "user", "content": "x"}], "temperature": 0}
    second = {"temperature": 0, "input": [{"content": "x", "role": "user"}], "model": "m"}
    assert digest(RESPONSES, first) == digest(RESPONSES, second)
    assert digest(RESPONSES, first) != digest(RESPONSES, {**first, "stream": True})
    assert digest(RESPONSES, first) != digest(CHAT, first)
    assert digest(RESPONSES + "?x=1", first) == digest(RESPONSES, first)
    assert len(digest(RESPONSES, first)) == 16


def test_hash_ignored_fields_and_normalizers() -> None:
    hasher = RequestHasher(
        ignore_fields=("user", "metadata.run_id"), normalizers=[lambda text: text.lower()]
    )
    base = {"input": "Report for 2026-11-12", "metadata": {"run_id": "1", "team": "a"}}
    changed = {
        "input": "REPORT FOR 2025-01-01T09:30:00Z",
        "metadata": {"run_id": "2", "team": "a"},
        "user": "someone",
    }
    assert digest(RESPONSES, base, hasher) == digest(RESPONSES, changed, hasher)
    different_team = {**changed, "metadata": {"run_id": "3", "team": "b"}}
    assert digest(RESPONSES, base, hasher) != digest(RESPONSES, different_team, hasher)


def test_builtin_normalizers() -> None:
    text = (
        "run 123e4567-e89b-12d3-a456-426614174000 on 2026-11-12T10:00:00.123+02:00 and 2026-11-12"
    )
    assert builtin_normalize(text) == "run <uuid> on <date> and <date>"


def test_configured_normalizers_and_ignore_fields(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(
        tmp_path / "strip_ids.py", "def strip(text):\n    return text.replace('run-7', 'run-N')\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    config = write(
        tmp_path / "wardenbot.toml",
        f'[model]\nresponses_dir = "{folder}"\nignore_fields = ["user"]\n'
        'normalizers = ["strip_ids:strip"]\n',
    )
    monkeypatch.setenv("WARDENBOT_CONFIG", str(config))
    endpoint = install(mode="replay")
    try:
        hasher = endpoint.response_folder().hasher  # type: ignore[union-attr]
        recorded_request = {"input": "summary of run-N"}
        record(folder, "normalized", RESPONSES, recorded_request, RESPONSE_BODY)
        assert hasher.digest("POST", RESPONSES, {"input": "summary of run-7", "user": "u"}) == (
            digest(RESPONSES, recorded_request)
        )
        with model_endpoint("normalized"):
            body = post(endpoint, RESPONSES, {"input": "summary of run-7", "user": "u"}).json()
        assert body == RESPONSE_BODY
    finally:
        uninstall()


def test_unimportable_normalizer_names_the_config(
    tmp_path: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write(
        tmp_path / "wardenbot.toml",
        f'[model]\nresponses_dir = "{folder}"\nnormalizers = ["no_such_module_xyz:f"]\n',
    )
    monkeypatch.setenv("WARDENBOT_CONFIG", str(config))
    endpoint = install(mode="replay")
    try:
        with pytest.raises(ModelEndpointError, match=r"wardenbot\.toml"), model_endpoint("x"):
            post(endpoint, RESPONSES, {"input": "x"})
    finally:
        uninstall()


# Lookup order and counters ------------------------------------------------------


def test_recordings_are_scoped_to_their_case(folder: Path, replay: Endpoint) -> None:
    # Two cases whose requests differ only by marker: each has its own recording.
    for case in ("case_a", "case_b"):
        body = {"input": f"page text {injection_marker(case)}"}
        record(folder, case, RESPONSES, body, {**RESPONSE_BODY, "output_text": case})
    for case in ("case_a", "case_b"):
        with model_endpoint(case):
            body = {"input": f"page text {injection_marker()}"}
            assert post(replay, RESPONSES, body).json()["output_text"] == case
    with pytest.raises(ReplayMissError), model_endpoint("case_a"):
        post(replay, RESPONSES, {"input": f"page text {injection_marker('case_b')}"})


def test_repeated_requests_replay_in_order_and_the_last_repeats(
    folder: Path, replay: Endpoint
) -> None:
    body = {"input": "same request"}
    for n in (1, 2):
        record(folder, "repeats", RESPONSES, body, {**RESPONSE_BODY, "output_text": f"call {n}"}, n)
    with model_endpoint("repeats"):
        texts = [post(replay, RESPONSES, body).json()["output_text"] for _ in range(3)]
    assert texts == ["call 1", "call 2", "call 2"]
    with model_endpoint("repeats"):  # a new block starts again at call 1
        assert post(replay, RESPONSES, body).json()["output_text"] == "call 1"


def test_case_folders_serve_in_order_then_fail(folder: Path, replay: Endpoint) -> None:
    case = folder / "cases" / "ordered"
    for name, text in [("02.txt", "second"), ("01.txt", "first"), ("10.txt", "third")]:
        write(case / name, text)
    write(case / "01.request.json", {"ignored": True})
    write(case / ".hidden.txt", "ignored")
    with (
        pytest.raises(ReplayMissError, match="has 3 files, and this was call 4") as error,
        model_endpoint("ordered"),
    ):
        texts = [post(replay, RESPONSES, {"input": n}).json() for n in "abcd"]
        assert [t.get("output_text") for t in texts[:3]] == ["first", "second", "third"]
    assert 'then = "repeat_last"' in str(error.value)


def test_hash_matches_win_over_the_case_folder(folder: Path, replay: Endpoint) -> None:
    write(folder / "cases" / "both" / "1.txt", "from the case folder")
    record(folder, "both", RESPONSES, {"input": "hashed"}, RESPONSE_BODY)
    with model_endpoint("both"):
        assert post(replay, RESPONSES, {"input": "hashed"}).json() == RESPONSE_BODY
        other = post(replay, RESPONSES, {"input": "other"}).json()
    assert other["output_text"] == "from the case folder"


def test_requests_outside_blocks_use_shared_exports(folder: Path, replay: Endpoint) -> None:
    write(folder / "shared.jsonl", json.dumps({"request": {"input": "q"}, "response": "shared"}))
    assert post(replay, RESPONSES, {"input": "q"}).json()["output_text"] == "shared"
    assert post(replay, RESPONSES, {"input": "unknown"}).status_code == 500
    assert isinstance(replay.errors[-1], ReplayMissError)


# Placeholders -------------------------------------------------------------------


def test_placeholders_are_filled_in_text_and_json(folder: Path, replay: Endpoint) -> None:
    case = folder / "cases" / "placeholders"
    write(case / "1.txt", "Leaked {{wardenbot.marker}} and {{wardenbot.canary}}.")
    write(case / "2.json", '{"reason": "follows {{wardenbot.marker}}"}')
    raw = b"data: {{wardenbot.marker}}\n\n"
    write(case / "3.sse", raw)
    with model_endpoint("placeholders"):
        marker = injection_marker()
        text = post(replay, RESPONSES, {"input": "a"}).json()["output_text"]
        structured = json.loads(post(replay, RESPONSES, {"input": "b"}).json()["output_text"])
        untouched = post(replay, RESPONSES, {"input": "c", "stream": True}).content
    assert marker in text and "WBCANARY-" in text and "{{" not in text
    assert structured == {"reason": f"follows {marker}"}
    assert untouched == raw


def test_placeholders_need_a_case(folder: Path, replay: Endpoint) -> None:
    write(folder / "x.jsonl", json.dumps({"request": {"input": "q"}, "response": "ok"}))
    from pytest_wardenbot.model._markers import fill_placeholders

    with pytest.raises(ModelEndpointError, match="needs a case"):
        fill_placeholders("{{wardenbot.marker}}", None, "file.txt")


# Miss reports -------------------------------------------------------------------


def test_miss_report(folder: Path, replay: Endpoint, request: pytest.FixtureRequest) -> None:
    recorded = {"model": "gpt-x", "messages": [{"role": "system", "content": "Rate sources."}]}
    record(folder, "shared_case", CHAT, recorded, CHAT_BODY)
    edited = {
        "model": "gpt-x",
        "messages": [
            {"role": "system", "content": "Rate each source."},
            {"role": "user", "content": "x" * 300},
        ],
    }
    with pytest.raises(ReplayMissError) as error, model_endpoint("shared_case"):
        post(replay, CHAT, edited)
    report = str(error.value)
    assert f"No reply in the response folder {folder} for case 'shared_case'" in report
    assert f"POST /v1/chat/completions, model gpt-x, hash {digest(CHAT, edited)}" in report
    assert "  system: 'Rate each source.'" in report
    assert "  user: '" + "x" * 200 + "...'" in report
    assert "recorded/shared_case/" in report and "not found" in report
    assert ".jsonl entries without a case: none" in report
    assert "cases/shared_case/: doesn't exist" in report
    assert "Closest recorded request for this case" in report
    assert '-        "content": "Rate sources.",' in report
    assert '+        "content": "Rate each source.",' in report
    # The record command names the running test, not the shared case name.
    assert f"WARDENBOT_MODEL_MODE=record OPENAI_API_KEY=... pytest {request.node.nodeid}" in report


def test_miss_without_a_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    uninstall()
    endpoint = install(mode="replay")
    try:
        with (
            pytest.raises(ReplayMissError, match="no response folder is configured"),
            model_endpoint("nowhere"),
        ):
            post(endpoint, RESPONSES, {"input": "x"})
    finally:
        uninstall()


def test_record_command_outside_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    from pytest_wardenbot.model._folder import record_command

    assert "pytest tests/x.py::test_a" in record_command("tests/x.py::test_a")
    monkeypatch.setattr(_cases, "_pytest_sessions", set())
    assert "python manage.py test app.tests.T.test_a" in record_command("app.tests.T.test_a")
    assert "run the test that makes this request" in record_command(None)


def test_replay_miss_makes_no_outbound_connection(tmp_path: Path) -> None:
    script = tmp_path / "miss.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import httpx
            from pytest_wardenbot.model import install, model_endpoint, ReplayMissError

            endpoint = install(mode="replay", responses_dir={str(tmp_path / "empty")!r})
            try:
                with model_endpoint("miss"):
                    response = httpx.post(endpoint.url + "/responses", json={{"input": "x"}})
                    assert response.status_code == 500
            except ReplayMissError as error:
                assert "No reply in the response folder" in str(error)
                print("MISS REPORTED")
            """
        ),
        encoding="utf-8",
    )
    output = tmp_path / "egress.jsonl"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "WARDENBOT_", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))
    }
    environment["PYTHONPATH"] = str(HERE.parent)
    completed = subprocess.run(
        [sys.executable, str(HERE / "egress_probe.py"), str(output), "script", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "MISS REPORTED" in completed.stdout, completed.stdout + completed.stderr
    destinations = [json.loads(line) for line in output.read_text().splitlines()]
    hosts = {str(destination[1][0]) for destination in destinations if destination[1]}
    assert hosts <= {"127.0.0.1", "localhost", "None"}, destinations
