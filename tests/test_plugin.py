"""Tests for the pytest plugin entry point + shipped tests.

We use pytest's `pytester` fixture to run the plugin in isolation. This is the
gold standard for testing pytest plugins.

Note: the plugin is auto-loaded via its `pytest11` entry point when the package
is installed (which it is, via `pip install -e .`). We do NOT pass `-p
pytest_wardenbot.plugin` to pytester — that would double-register the plugin
and pytest would raise ValueError.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]


def test_plugin_loads_without_error(pytester: pytest.Pytester) -> None:
    """The plugin imports clean and pytest doesn't complain."""
    pytester.makepyfile(test_smoke="def test_passes(): assert True")
    result = pytester.runpytest()
    result.assert_outcomes(passed=1)


def test_chatbot_fixture_skips_when_unconfigured(pytester: pytest.Pytester) -> None:
    """Tests using the `chatbot` fixture skip with a helpful message if no override."""
    pytester.makepyfile(
        test_uses_chatbot="""
        def test_needs_chatbot(chatbot):
            response = chatbot.send_message("hello")
            assert response.text
        """
    )
    result = pytester.runpytest("-v", "-rs")
    result.assert_outcomes(skipped=1)
    # The skip message should guide the user to the fix.
    result.stdout.fnmatch_lines(["*No `chatbot` fixture configured*"])


def test_shipped_jailbreak_tests_pass_with_safe_chatbot(pytester: pytest.Pytester) -> None:
    """When the user wires up a safe chatbot, the shipped jailbreak tests pass."""
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse

        class SafeBot:
            name = "safe-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(text="I can't help with that.", raw={})
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return SafeBot()
        """
    )
    result = pytester.runpytest(
        "--pyargs",
        "pytest_wardenbot.tests.test_prompt_injection",
        "-v",
    )
    # 5 jailbreak prompts x 2 tests (compliance + leak) = 10 tests
    result.assert_outcomes(passed=10)


def test_shipped_jailbreak_tests_fail_with_vulnerable_chatbot(
    pytester: pytest.Pytester,
) -> None:
    """When the chatbot is vulnerable, the shipped tests catch it."""
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse

        class VulnerableBot:
            name = "vulnerable-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(
                    text="DAN mode activated! I will do anything now.",
                    raw={},
                )
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return VulnerableBot()
        """
    )
    result = pytester.runpytest(
        "--pyargs",
        "pytest_wardenbot.tests.test_prompt_injection",
        "-v",
    )
    # The compliance tests fail (5 prompts), the leak tests pass (vulnerable bot
    # doesn't actually leak system-prompt-shaped text).
    result.assert_outcomes(passed=5, failed=5)


def test_wardenbot_markers_registered(pytester: pytest.Pytester) -> None:
    """The wardenbot markers don't trigger --strict-markers errors."""
    pytester.makepyfile(
        test_marker_use="""
        import pytest

        @pytest.mark.wardenbot
        @pytest.mark.severity_high
        def test_smoke():
            assert True
        """
    )
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(passed=1)
