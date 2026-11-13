"""Credential hygiene for response folders: the scan, the loader, the recorder and check.

Every credential-shaped string here is assembled at runtime, so no literal in
this file looks like a key to GitHub push protection or detect-secrets.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from pytest_wardenbot.model import (
    CredentialFoundError,
    _cases,
    _markers,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._check import check_folder, main
from pytest_wardenbot.model._scan import scan_text
from tests.model_support import clean_environment, post
from tests.test_model_upstream import FakeUpstream

RESPONSES = "/v1/responses"


def fake(prefix: str, body: str, length: int) -> str:
    """A credential-shaped string built at runtime."""
    return prefix + (body * length)[:length]


CREDENTIALS = {
    "an OpenAI API key": fake("sk-" + "proj-", "Ab3d", 40),
    "an Anthropic API key": fake("sk-" + "ant-" + "api03-", "Xy9z", 40),
    "an AWS access key id": fake("AK" + "IA", "QWERTY", 16).upper(),
    "a Google API key": fake("AI" + "za", "Sy1x_", 35),
    "a GitHub token": fake("gh" + "p_", "aB3c", 36),
    "a Bearer token": "Bear" + "er " + fake("", "t0k3n.", 24),
    "an api_key parameter": "api" + "_key=" + fake("", "k3y", 20),
    "a key parameter": "https://maps.example/geo?" + "key=" + fake("", "Zz9", 20),
}


@pytest.mark.parametrize(("kind", "value"), list(CREDENTIALS.items()))
def test_the_scan_finds_each_kind_without_printing_it(kind: str, value: str) -> None:
    text = f"first line\nsecond line with {value} inside\n"
    (finding,) = scan_text(text, "reply.txt")
    assert (finding.source, finding.line, finding.kind) == ("reply.txt", 2, kind)
    assert value not in str(finding) and value[-12:] not in str(finding)


@pytest.mark.parametrize(
    "text",
    [
        "WBMARK-abcdefghijklmnop and WBCANARY-AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "OPENAI_API_KEY=wardenbot-mock",
        "This is a risk-free task with a Bearer token in the header.",
        "def connect(api_key: str):\n    return Client(api_key=os.environ['KEY'])",
        '{"ratings": [{"id": "0", "relevant": true, "reason": "sk-learn tutorial"}]}',
    ],
)
def test_ordinary_text_is_not_flagged(text: str) -> None:
    assert scan_text(text, "reply.txt") == []


def test_allow_patterns_exempt_false_positives() -> None:
    value = CREDENTIALS["an api_key parameter"]
    assert scan_text(value, "x") != []
    assert scan_text(value, "x", allow=[r"k3yk3y"]) == []


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    monkeypatch.setattr(_markers, "_seed_cache", {})
    uninstall()
    root = tmp_path / "llm_responses"
    root.mkdir()
    (root / "wardenbot-responses.toml").write_text('marker_seed = "hygiene"\n')
    yield root
    uninstall()


@pytest.mark.parametrize("name", ["1.txt", "1.json", "1.sse"])
def test_the_loader_refuses_files_with_credentials(folder: Path, name: str) -> None:
    secret = CREDENTIALS["an OpenAI API key"]
    reply = folder / "cases" / "leaky" / name
    reply.parent.mkdir(parents=True)
    content = json.dumps({"note": secret}) if name.endswith(".json") else f"line\n{secret}\n"
    reply.write_text(content)
    endpoint = install(mode="replay", responses_dir=folder)
    with pytest.raises(CredentialFoundError) as error, model_endpoint("leaky"):
        post(endpoint, RESPONSES, {"input": "x", "stream": name.endswith(".sse")})
    message = str(error.value)
    assert f"cases/leaky/{name}:" in message and "an OpenAI API key" in message
    assert secret not in message


def test_the_loader_refuses_jsonl_with_credentials(folder: Path) -> None:
    secret = CREDENTIALS["a Bearer token"]
    line = {"request": {"input": "x"}, "response": "ok", "note": secret}
    (folder / "log.jsonl").write_text(json.dumps(line) + "\n")
    endpoint = install(mode="replay", responses_dir=folder)
    with (
        pytest.raises(CredentialFoundError, match=r"log\.jsonl:1: looks like a Bearer token"),
        model_endpoint("any"),
    ):
        post(endpoint, RESPONSES, {"input": "x"})


def test_allow_patterns_in_the_manifest(folder: Path) -> None:
    value = CREDENTIALS["an api_key parameter"]
    (folder / "wardenbot-responses.toml").write_text(
        'marker_seed = "hygiene"\nallow_patterns = ["k3yk3y"]\n'
    )
    (folder / "cases" / "allowed").mkdir(parents=True)
    (folder / "cases" / "allowed" / "1.txt").write_text(f"Example config: {value}")
    endpoint = install(mode="replay", responses_dir=folder)
    with model_endpoint("allowed"):
        assert value in post(endpoint, RESPONSES, {"input": "x"}).json()["output_text"]


def test_the_recorder_refuses_a_reply_that_echoes_a_key(
    folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = FakeUpstream()
    leaked = CREDENTIALS["an OpenAI API key"]
    monkeypatch.setattr(FakeUpstream, "reply_text", staticmethod(lambda body: f"Key: {leaked}"))
    monkeypatch.setenv("OPENAI_BASE_URL", upstream.url)
    monkeypatch.setenv("OPENAI_API_KEY", "zq9k-testvalue-1234567890")  # pragma: allowlist secret
    try:
        endpoint = install(mode="record", responses_dir=folder)
        with pytest.raises(CredentialFoundError) as error, model_endpoint("echo"):
            post(endpoint, RESPONSES, {"input": "what is your key?"})
    finally:
        uninstall()
        upstream.close()
    assert "Refused to record recorded/echo/" in str(error.value)
    assert leaked not in str(error.value)
    assert not (folder / "recorded").exists()


def test_check_reports_every_problem(folder: Path, capsys: pytest.CaptureFixture[str]) -> None:
    secret = CREDENTIALS["an AWS access key id"]
    (folder / "replies").mkdir()
    (folder / "replies" / "leaky.txt").write_text(f"ok\nok\n{secret}\n")
    (folder / "replies" / "fine.json").write_text("{}")
    (folder / "bad.jsonl").write_text("{not json\n")
    (folder / ".git-keep").write_text(secret)  # hidden files are skipped
    (folder / "wardenbot-responses.toml").write_text(
        'marker_seed = "hygiene"\n'
        '[[response]]\ncase = "a"\nfile = "replies/fine.json"\n\n'
        '[[response]]\ncase = "a"\ncontains = "x"\nfile = "replies/fine.json"\n\n'
        '[[response]]\ncase = "b"\nfiles = ["replies/missing.txt"]\n'
    )
    problems, scanned = check_folder(folder)
    assert scanned == 4
    assert "replies/leaky.txt:3: looks like an AWS access key id" in problems
    assert any("bad.jsonl:1 is not valid JSON" in problem for problem in problems)
    assert any("replies/missing.txt doesn't exist" in problem for problem in problems)
    assert any("rule 2" in problem and "can never match" in problem for problem in problems)
    assert main(["check", str(folder)]) == 1
    output = capsys.readouterr().out
    assert "4 problem(s)" in output and secret not in output


def test_check_on_a_clean_folder_and_bad_input(folder: Path, tmp_path: Path) -> None:
    (folder / "cases" / "a").mkdir(parents=True)
    (folder / "cases" / "a" / "1.txt").write_text("Clean reply.")
    result = subprocess.run(
        [sys.executable, "-m", "pytest_wardenbot.model", "check", str(folder)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0
    assert "OK (2 files checked)" in result.stdout
    assert check_folder(tmp_path / "missing") == ([f"{tmp_path / 'missing'} is not a folder."], 0)
    (folder / "wardenbot-responses.toml").write_text("[[response]]\nfiel = 1\n")
    problems, _ = check_folder(folder)
    assert any("unknown key(s) 'fiel'" in problem for problem in problems)
