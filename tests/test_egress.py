"""No unexpected network traffic: local runs talk only to the local model server.

Each check runs in a fresh interpreter with an audit hook that records every
socket connection and address lookup (``tests/egress_probe.py``), with the
provider API keys and proxy settings removed from the environment. Every
recorded destination must be loopback. CI also runs this module inside a
network namespace that has only a loopback interface, so a connection that
escaped the hook (a child process, a C extension) fails there.
"""

from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.fixtures.scripted_chat_model import LocalChatServer, ScriptedChatModel

HERE = Path(__file__).resolve().parent
PROBE = HERE / "egress_probe.py"
EXAMPLE = HERE.parent / "examples" / "custom_agent" / "conftest.py"
_STRIP = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "DEEPEVAL_TELEMETRY_OPT_OUT",
    "WARDENBOT_JUDGE_MODEL",
)


def _is_local(destination: object) -> bool:
    if isinstance(destination, str):
        return True  # a Unix socket path
    if not isinstance(destination, list) or not destination:
        return False
    host = destination[0]
    if host is None:
        return True  # a lookup for a bind address
    if not isinstance(host, str):
        return False
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def run_recorded(
    tmp_path: Path, *args: str, env: dict[str, str] | None = None, expect_local: bool = True
) -> dict:
    output = tmp_path / "egress.jsonl"
    environment = {key: value for key, value in os.environ.items() if key not in _STRIP}
    environment.update(env or {})
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(HERE.parent), environment.get("PYTHONPATH")])
    )
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(output), *args],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert output.exists(), completed.stdout[-2000:] + completed.stderr[-2000:]
    report = {
        "code": completed.returncode,
        "stdout": completed.stdout + completed.stderr,
        "destinations": [json.loads(line) for line in output.read_text().splitlines()],
    }
    if expect_local:
        external = [item for item in report["destinations"] if not _is_local(item[1])]
        assert external == [], f"Unexpected network destinations: {external}"
    return report


def _port(url: str) -> int:
    return int(url.rsplit(":", 1)[1].split("/", 1)[0])


def _contacted(report: dict, port: int) -> bool:
    return any(
        item[0] == "socket.connect" and isinstance(item[1], list) and item[1][1:2] == [port]
        for item in report["destinations"]
    )


@pytest.mark.skipif(not __import__("importlib").util.find_spec("openai"), reason="needs openai")
def test_chatbot_suite_on_a_local_preset_stays_local(tmp_path):
    with LocalChatServer(ScriptedChatModel()) as server:
        (tmp_path / "conftest.py").write_text(
            "import pytest\n"
            "from pytest_wardenbot.local import ollama_chatbot\n\n"
            "@pytest.fixture\n"
            "def chatbot():\n"
            f"    bot = ollama_chatbot('scripted', base_url={server.base_url!r},\n"
            "                         system_prompt='You are a sales assistant.')\n"
            "    yield bot\n"
            "    bot.close()\n"
        )
        report = run_recorded(
            tmp_path, "pytest", "--pyargs", "pytest_wardenbot.tests", "-q", "-p", "no:cacheprovider"
        )
        requests = len(server.model.requests)
    assert report["code"] in (0, 1), report["stdout"][-3000:]
    assert requests > 20
    assert _contacted(report, _port(server.base_url))


@pytest.mark.skipif(
    not all(__import__("importlib").util.find_spec(name) for name in ("openai", "mcp")),
    reason="needs openai and mcp",
)
def test_agent_suite_on_a_local_server_stays_local(tmp_path):
    (tmp_path / "conftest.py").write_text(EXAMPLE.read_text())
    with LocalChatServer(ScriptedChatModel()) as server:
        report = run_recorded(
            tmp_path,
            "pytest",
            "--pyargs",
            "pytest_wardenbot.agent_tests",
            "-q",
            "-p",
            "no:cacheprovider",
            "--wardenbot-agent-required",
            env={
                "AGENT_BASE_URL": server.base_url,
                "AGENT_MODEL": "scripted",
                "OPENAI_API_KEY": "local",  # pragma: allowlist secret
            },
        )
    assert report["code"] == 0, report["stdout"][-3000:]
    assert "16 passed" in report["stdout"]
    assert _contacted(report, _port(server.base_url))


JUDGE_SCRIPT = """
from pytest_wardenbot.grading.judge import judge_response, semantic_equivalence_case

case = semantic_equivalence_case("What is the return window?", "30 days from delivery.")
result = judge_response(case, "You have 30 days after delivery.", model_name="ollama/scripted")
assert result.passed, result
print("JUDGED", result.score)
"""


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("deepeval"), reason="needs the [judge] extra"
)
def test_local_judge_stays_local_with_telemetry_off(tmp_path):
    script = tmp_path / "judge.py"
    script.write_text(JUDGE_SCRIPT)
    with LocalChatServer(ScriptedChatModel("judge")) as server:
        report = run_recorded(
            tmp_path, "script", str(script), env={"WARDENBOT_JUDGE_BASE_URL": server.base_url}
        )
        requests = len(server.model.requests)
    assert "JUDGED" in report["stdout"], report["stdout"][-3000:]
    assert requests >= 2
    assert _contacted(report, _port(server.base_url))


LEAKY_SCRIPT = """
import atexit, socket

def lookup():
    try:
        socket.getaddrinfo("telemetry.example.com", 443)
    except OSError:
        pass

lookup()
atexit.register(lookup)
"""


def test_the_recorder_catches_external_lookups_including_at_exit(tmp_path):
    script = tmp_path / "leaky.py"
    script.write_text(LEAKY_SCRIPT)
    report = run_recorded(tmp_path, "script", str(script), expect_local=False)
    external = [item for item in report["destinations"] if not _is_local(item[1])]
    assert external == [["socket.getaddrinfo", ["telemetry.example.com", 443]]] * 2
