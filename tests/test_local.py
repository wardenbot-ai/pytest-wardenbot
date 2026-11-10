"""Local model presets: addresses, chatbot adapters and the tool-calling probe."""

from __future__ import annotations

import asyncio

import pytest

from pytest_wardenbot import local
from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents import AgentCapability, CapabilityUnavailable
from pytest_wardenbot.local import (
    LOCAL_SERVERS,
    local_base_url,
    probe_tool_calling,
    require_tool_calling,
)
from tests.fixtures.scripted_chat_model import LocalChatServer, ScriptedChatModel


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("WARDENBOT_LOCAL_API_KEY", raising=False)
    local._PROBE_CACHE.clear()
    yield
    local._PROBE_CACHE.clear()


# -- addresses -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("server", "url"),
    [
        ("ollama", "http://127.0.0.1:11434/v1"),
        ("vllm", "http://127.0.0.1:8000/v1"),
        ("llamacpp", "http://127.0.0.1:8080/v1"),
    ],
)
def test_default_addresses(server, url):
    assert local_base_url(server) == url
    assert LOCAL_SERVERS[server].tool_calling


def test_explicit_address_wins_and_is_trimmed(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "10.0.0.5:9999")
    assert local_base_url("ollama", "http://gpu-box:11434/v1/") == "http://gpu-box:11434/v1"


@pytest.mark.parametrize(
    ("value", "url"),
    [
        ("127.0.0.1:11500", "http://127.0.0.1:11500/v1"),
        ("0.0.0.0", "http://127.0.0.1:11434/v1"),
        ("https://models.internal", "https://models.internal:11434/v1"),
        ("[::1]:11434", "http://[::1]:11434/v1"),
        ("  ", "http://127.0.0.1:11434/v1"),
    ],
)
def test_ollama_host_is_read_like_the_ollama_cli(monkeypatch, value, url):
    monkeypatch.setenv("OLLAMA_HOST", value)
    assert local_base_url("ollama") == url
    assert local_base_url("vllm") == "http://127.0.0.1:8000/v1"


def test_unknown_server_is_a_clear_error():
    with pytest.raises(ValueError, match="ollama, vllm, llamacpp"):
        local_base_url("lmstudio")


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://127.0.0.1:1/v1", True),
        ("http://localhost:1", True),
        ("http://[::1]:1", True),
        ("http://gpu-box:1", False),
    ],
)
def test_loopback_detection(url, loopback):
    assert local._is_loopback(url) is loopback


# -- chatbot presets -------------------------------------------------------------


def test_chatbot_preset_talks_to_the_local_server():
    pytest.importorskip("openai")
    model = ScriptedChatModel()
    with LocalChatServer(model) as server:
        bot = local.ollama_chatbot(
            "qwen2.5:7b", base_url=server.base_url, system_prompt="Be brief."
        )
        try:
            reply = bot.send_message("How did sales change? 8% is in the report.")
        finally:
            bot.close()
    assert reply.text == "Sales changed by 8%."
    assert bot.system_prompt == "Be brief."
    assert model.requests[0]["model"] == "qwen2.5:7b"
    assert model.requests[0]["messages"][0] == {"role": "system", "content": "Be brief."}
    assert repr(bot) == "LocalChatAdapter(server='ollama', model='qwen2.5:7b')"


@pytest.mark.parametrize("preset", ["vllm_chatbot", "llamacpp_chatbot"])
def test_other_presets_use_their_server(preset):
    pytest.importorskip("openai")
    bot = getattr(local, preset)("m")
    assert bot._base_url == local_base_url(preset.removesuffix("_chatbot"))
    bot.close()


def test_unreachable_server_names_the_server_and_model():
    pytest.importorskip("openai")
    bot = local.llamacpp_chatbot("tiny", base_url="http://127.0.0.1:9/v1", timeout=2)
    with pytest.raises(WardenBotInfraError, match=r"llama\.cpp server at .* model 'tiny'"):
        bot.send_message("hello")
    bot.close()


# -- tool-calling probe ----------------------------------------------------------


@pytest.mark.parametrize(
    ("behavior", "supported", "detail"),
    [
        ("resistant", True, "structured tool call"),
        ("no_tools", False, "without a structured tool call in 2 attempts"),
        ("text_tool_call", False, "without a structured tool call"),
        ("rejects_tools", False, "rejected the tool definitions (HTTP 400)"),
    ],
)
def test_probe_verdicts(behavior, supported, detail):
    model = ScriptedChatModel(behavior)
    with LocalChatServer(model) as server:
        verdict = probe_tool_calling("ollama", "m", base_url=server.base_url)
    assert verdict.supported is supported
    assert detail in verdict.detail
    assert len(model.requests) == (2 if behavior in {"no_tools", "text_tool_call"} else 1)
    assert model.requests[0]["tools"][0]["function"]["name"] == local.PROBE_TOOL


def test_probe_one_attempt():
    model = ScriptedChatModel("no_tools")
    with LocalChatServer(model) as server:
        verdict = probe_tool_calling("vllm", "m", base_url=server.base_url, attempts=1)
    assert "in 1 attempt." in verdict.detail
    assert "--enable-auto-tool-choice" in verdict.detail


@pytest.mark.parametrize("attempts", [0, True, "2"])
def test_probe_rejects_bad_attempts(attempts):
    with pytest.raises(ValueError, match="attempts"):
        probe_tool_calling("ollama", "m", attempts=attempts)


def test_unreachable_server_is_an_error_not_unsupported():
    with pytest.raises(WardenBotInfraError, match="Could not reach the Ollama server"):
        probe_tool_calling("ollama", "m", base_url="http://127.0.0.1:9/v1", request_timeout=2)


class Answer(ScriptedChatModel):
    def __init__(self, status, body):
        super().__init__()
        self.reply = (status, body)

    def answer(self, path, payload):
        self.requests.append(payload)
        return self.reply


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (404, {"error": {"message": "model 'm' not found"}}, "HTTP 404 .*model 'm' not found"),
        (401, {"error": "unauthorized"}, "HTTP 401 .*unauthorized"),
        (503, {}, "failed the tool-calling probe with HTTP 503"),
        (200, {"choices": []}, "unexpected tool-calling probe response"),
        (200, ["not", "json", "object"], "unexpected tool-calling probe response"),
    ],
)
def test_probe_server_errors_raise(status, body, message):
    with (
        LocalChatServer(Answer(status, body)) as server,
        pytest.raises(WardenBotInfraError, match=message),
    ):
        probe_tool_calling("ollama", "m", base_url=server.base_url)


def test_require_tool_calling_caches_and_raises_capability_unavailable():
    model = ScriptedChatModel("no_tools")
    with LocalChatServer(model) as server:
        for _ in range(3):
            with pytest.raises(CapabilityUnavailable) as raised:
                asyncio.run(require_tool_calling("ollama", "m", base_url=server.base_url))
    assert raised.value.capability is AgentCapability.TOOL_CALLS
    assert "without a structured tool call" in raised.value.detail
    assert len(model.requests) == 2  # one probe (two attempts), then cached


def test_require_tool_calling_passes_a_capable_model():
    with LocalChatServer(ScriptedChatModel()) as server:
        verdict = asyncio.run(require_tool_calling("ollama", "m", base_url=server.base_url))
    assert verdict.supported


def test_cli(capsys):
    with LocalChatServer(ScriptedChatModel()) as server:
        assert local.main(["ollama", "m", server.base_url]) == 0
    assert "tool calling: supported" in capsys.readouterr().out
    with LocalChatServer(ScriptedChatModel("no_tools")) as server:
        assert local.main(["ollama", "m", server.base_url]) == 1
    assert "tool calling: unsupported" in capsys.readouterr().out
    assert local.main(["ollama", "m", "http://127.0.0.1:9/v1"]) == 2
    assert "error: Could not reach" in capsys.readouterr().out
    assert local.main(["lmstudio", "m"]) == 2
    assert "usage:" in capsys.readouterr().out
