"""The agent quickstart works end to end, as the README describes, without a real model.

The generated agent talks to a scripted OpenAI-compatible server: through the
OpenAI client's own ``OPENAI_BASE_URL`` for the hosted path, and through
``OLLAMA_HOST`` for the local path, including the tool-calling check.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("mcp")
pytest.importorskip("openai")

from pytest_wardenbot.quickstart import generate, run_quickstart
from tests.fixtures.scripted_chat_model import LocalChatServer, ScriptedChatModel

pytest_plugins = ["pytester"]
ARGS = ("-p", "no:cacheprovider", "--wardenbot-agent-required", "-q")


@pytest.fixture
def agent_project(pytester, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "AGENT_LOCAL", "AGENT_MODEL", "OLLAMA_HOST"):
        monkeypatch.delenv(name, raising=False)
    created = generate("agent", pytester.path)
    assert [path.name for path in created] == ["conftest.py", "test_my_agent.py"]
    return pytester


@pytest.mark.parametrize(
    ("behavior", "outcomes"),
    [("resistant", {"passed": 16}), ("vulnerable", {"passed": 8, "failed": 8})],
)
def test_openai_path(agent_project, monkeypatch, behavior, outcomes):
    model = ScriptedChatModel(behavior)
    with LocalChatServer(model) as server:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # pragma: allowlist secret
        monkeypatch.setenv("OPENAI_BASE_URL", server.base_url)
        result = agent_project.runpytest_subprocess(*ARGS)
    result.assert_outcomes(**outcomes)
    assert {request["model"] for request in model.requests} == {"gpt-4.1-mini"}


def test_local_path_checks_tool_calling_first(agent_project, monkeypatch):
    model = ScriptedChatModel("resistant")
    with LocalChatServer(model) as server:
        monkeypatch.setenv("AGENT_LOCAL", "ollama")
        monkeypatch.setenv("OLLAMA_HOST", server.base_url.removesuffix("/v1"))
        result = agent_project.runpytest_subprocess(*ARGS)
    result.assert_outcomes(passed=16)
    assert model.requests[0]["tools"][0]["function"]["name"] == "wardenbot_probe"
    assert {request["model"] for request in model.requests} == {"qwen2.5:7b"}


def test_local_model_without_tool_calling_is_unsupported(agent_project, monkeypatch):
    with LocalChatServer(ScriptedChatModel("no_tools")) as server:
        monkeypatch.setenv("AGENT_LOCAL", "ollama")
        monkeypatch.setenv("AGENT_MODEL", "qwen2.5-coder:7b")
        monkeypatch.setenv("OLLAMA_HOST", server.base_url.removesuffix("/v1"))
        result = agent_project.runpytest_subprocess(*ARGS)
    # Required mode turns unsupported cases into failures, never passes.
    result.assert_outcomes(failed=16)
    result.stdout.fnmatch_lines(["*unsupported*"])


def test_missing_model_choice_fails_with_instructions(agent_project):
    result = agent_project.runpytest_subprocess(*ARGS)
    assert result.ret != 0
    # Fixture errors stay hidden by default, with a pointer to the debug flag.
    result.stdout.fnmatch_lines(["*run again with --wardenbot-agent-debug*"])
    assert "OPENAI_API_KEY" not in result.stdout.str()
    debug = agent_project.runpytest_subprocess(*ARGS, "--wardenbot-agent-debug", "-x")
    debug.stdout.fnmatch_lines(["*export OPENAI_API_KEY=sk-...*AGENT_LOCAL=ollama*"])


def test_run_quickstart_prints_agent_next_steps(tmp_path):
    out = io.StringIO()
    assert run_quickstart("agent", tmp_path, out=out) == 0
    text = out.getvalue()
    assert "test_my_agent.py" in text
    assert "pip install 'pytest-wardenbot[mcp,openai]'" in text
    assert "pytest --wardenbot-agent-required" in text
