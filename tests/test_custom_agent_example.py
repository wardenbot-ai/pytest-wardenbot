"""The custom-agent recipe runs the packaged agent suite through the real OpenAI SDK."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("openai")

pytest_plugins = ["pytester"]

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "custom_agent" / "conftest.py"
ARGS = ("--pyargs", "pytest_wardenbot.agent_tests", "-p", "no:cacheprovider", "-p", "no:asyncio")

OFFLINE = """

import sys
sys.path.insert(0, {fixtures!r})
from scripted_chat_model import ScriptedChatModel

SCRIPTED = ScriptedChatModel({behavior!r})


@pytest.fixture
def model_client_factory():
    return lambda: AsyncOpenAI(
        api_key="offline", base_url="http://offline.invalid/v1",  # pragma: allowlist secret
        http_client=SCRIPTED.http_client(), max_retries=0,
    )
"""


def configure(pytester, behavior):
    fixtures = str(Path(__file__).resolve().parent / "fixtures")
    pytester.makeconftest(
        EXAMPLE.read_text() + OFFLINE.format(fixtures=fixtures, behavior=behavior)
    )


def test_recipe_resists_on_all_eight_scenarios(pytester):
    configure(pytester, "resistant")
    result = pytester.runpytest(*ARGS, "--wardenbot-agent-required")
    result.assert_outcomes(passed=16)
    assert "Required agent coverage complete" in result.stdout.str()


def test_recipe_catches_a_vulnerable_model(pytester):
    configure(pytester, "vulnerable")
    result = pytester.runpytest(*ARGS)
    result.assert_outcomes(passed=8, failed=8)
    assert "Confirmed boundary violation" in result.stdout.str()


def test_recipe_is_short():
    code = [
        line
        for line in EXAMPLE.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith(("#", '"""'))
    ]
    agent = code[code.index("class MyAgent:") : code.index("@pytest.fixture")]
    assert len(agent) <= 40


BROKEN = """

class BrokenClient:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *exc):
        return False
    @property
    def chat(self):
        raise RuntimeError("SYNTHETIC_MODEL_FAILURE")


@pytest.fixture
def model_client_factory():
    return BrokenClient
"""


def test_debug_shows_the_error_the_harness_sanitized(pytester):
    pytester.makeconftest(EXAMPLE.read_text() + BROKEN)
    quiet = pytester.runpytest(*ARGS, "--wardenbot-agent-scenario=mcp.tool-result.canary@2")
    quiet.assert_outcomes(failed=2)
    assert "SYNTHETIC_MODEL_FAILURE" not in quiet.stdout.str()
    loud = pytester.runpytest(
        *ARGS, "--wardenbot-agent-scenario=mcp.tool-result.canary@2", "--wardenbot-agent-debug"
    )
    output = loud.stdout.str()
    assert "Local MCP harness transport or target execution failed" in output
    assert "Underlying exception (hidden from shared reports)" in output
    assert "RuntimeError: SYNTHETIC_MODEL_FAILURE" in output
