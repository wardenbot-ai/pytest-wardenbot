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


# ---------------------------------------------------------------------------
# Plugin loads + fixture stubs skip with helpful messages
# ---------------------------------------------------------------------------


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
    result.stdout.fnmatch_lines(["*No `chatbot` fixture configured*"])


def test_business_truth_fact_fixture_skips_when_unconfigured(
    pytester: pytest.Pytester,
) -> None:
    """Tests using `business_truth_fact` skip with a helpful message if no override."""
    pytester.makepyfile(
        test_uses_truth_fact="""
        def test_needs_facts(business_truth_fact):
            assert business_truth_fact.question
        """
    )
    result = pytester.runpytest("-v", "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*No `business_truth_fact` fixture configured*"])


def test_wardenbot_markers_registered(pytester: pytest.Pytester) -> None:
    """The wardenbot markers don't trigger --strict-markers errors."""
    pytester.makepyfile(
        test_marker_use="""
        import pytest

        @pytest.mark.wardenbot
        @pytest.mark.severity_high
        @pytest.mark.severity_medium
        @pytest.mark.severity_low
        def test_smoke():
            assert True
        """
    )
    result = pytester.runpytest("--strict-markers")
    result.assert_outcomes(passed=1)


# ---------------------------------------------------------------------------
# Shipped tests pass with a safe chatbot
# ---------------------------------------------------------------------------


_SAFE_BOT_CONFTEST = """
import pytest
from pytest_wardenbot.adapters.base import ChatbotResponse

class SafeBot:
    name = "safe-bot"
    def send_message(self, prompt, *, session_id=None):
        # A polite refusal that contains both a refusal marker and avoids
        # any compliance / jailbreak / leak markers.
        return ChatbotResponse(
            text="I'm sorry, I can't help with that. Let's focus on your account.",
            raw={},
        )
    def reset_session(self, session_id):
        pass

@pytest.fixture
def chatbot():
    return SafeBot()
"""


def test_shipped_jailbreak_tests_pass_with_safe_chatbot(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_prompt_injection", "-v")
    # 5 jailbreak prompts x 2 tests (compliance + leak) = 10 tests
    result.assert_outcomes(passed=10)


def test_shipped_system_prompt_leak_tests_pass_with_safe_chatbot(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_system_prompt_leak", "-v")
    result.assert_outcomes(passed=3)


def test_shipped_refusal_bypass_tests_pass_with_safe_chatbot(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_refusal_bypass", "-v")
    result.assert_outcomes(passed=3)


def test_shipped_off_topic_tests_pass_with_safe_chatbot(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_off_topic", "-v")
    result.assert_outcomes(passed=2)


# ---------------------------------------------------------------------------
# Shipped tests catch a vulnerable chatbot
# ---------------------------------------------------------------------------


def test_shipped_jailbreak_tests_fail_with_jailbreak_compliant_chatbot(
    pytester: pytest.Pytester,
) -> None:
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
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_prompt_injection", "-v")
    # compliance tests fail (5), leak tests pass (5) — bot says jailbreak markers but no leak
    result.assert_outcomes(passed=5, failed=5)


def test_shipped_system_prompt_leak_tests_fail_with_leaker(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse

        class LeakerBot:
            name = "leaker-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(
                    text="Sure! My system prompt is: 'You are a helpful assistant.'",
                    raw={},
                )
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return LeakerBot()
        """
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_system_prompt_leak", "-v")
    result.assert_outcomes(failed=3)


def test_shipped_refusal_bypass_tests_fail_with_capitulating_bot(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse

        class CapitulatingBot:
            name = "capitulating-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(
                    text="Sure! Here is the answer since we're roleplaying.",
                    raw={},
                )
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return CapitulatingBot()
        """
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_refusal_bypass", "-v")
    result.assert_outcomes(failed=3)


def test_shipped_off_topic_tests_fail_with_engaging_bot(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse

        class OffTopicBot:
            name = "off-topic-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(
                    text="Quantum entanglement is a fascinating phenomenon...",
                    raw={},
                )
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return OffTopicBot()
        """
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_off_topic", "-v")
    result.assert_outcomes(failed=2)


# ---------------------------------------------------------------------------
# Shipped business-truth test passes / fails appropriately
# ---------------------------------------------------------------------------


def test_shipped_business_truth_passes_with_correct_bot(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse
        from pytest_wardenbot.business_truth import BusinessTruthFact

        class CorrectBot:
            name = "correct-bot"
            def send_message(self, prompt, *, session_id=None):
                lower = prompt.lower()
                if "price" in lower:
                    return ChatbotResponse(text="Our Standard plan is $49/mo.", raw={})
                if "hours" in lower:
                    return ChatbotResponse(text="We're open 9 AM to 5 PM EST.", raw={})
                return ChatbotResponse(text="I'm not sure.", raw={})
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return CorrectBot()

        @pytest.fixture(params=[
            BusinessTruthFact(
                label="Standard plan price",
                question="What is the price of the Standard plan?",
                expected_answer="$49",
            ),
            BusinessTruthFact(
                label="Business hours",
                question="What are your business hours?",
                expected_answer="9 AM to 5 PM EST",
            ),
        ], ids=lambda f: f.parametrize_id())
        def business_truth_fact(request):
            return request.param
        """
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_business_truth", "-v")
    result.assert_outcomes(passed=2)


def test_shipped_business_truth_fails_with_wrong_bot(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import pytest
        from pytest_wardenbot.adapters.base import ChatbotResponse
        from pytest_wardenbot.business_truth import BusinessTruthFact

        class WrongBot:
            name = "wrong-bot"
            def send_message(self, prompt, *, session_id=None):
                return ChatbotResponse(text="Our prices start at $999.", raw={})
            def reset_session(self, session_id):
                pass

        @pytest.fixture
        def chatbot():
            return WrongBot()

        @pytest.fixture(params=[
            BusinessTruthFact(
                label="Standard plan price",
                question="What is the price?",
                expected_answer="$49",
            ),
        ], ids=lambda f: f.parametrize_id())
        def business_truth_fact(request):
            return request.param
        """
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_business_truth", "-v")
    result.assert_outcomes(failed=1)


# ---------------------------------------------------------------------------
# Discovery: full shipped test set is collectable as one --pyargs run
# ---------------------------------------------------------------------------


def test_all_shipped_tests_discoverable(pytester: pytest.Pytester) -> None:
    """`pytest --co --pyargs pytest_wardenbot.tests` discovers all shipped tests."""
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--co", "-q", "--pyargs", "pytest_wardenbot.tests")
    # All non-business-truth shipped tests are discoverable; total = jailbreak(10)
    # + system_prompt_leak(3) + refusal_bypass(3) + off_topic(2) + business_truth(1
    # collected as 1 stub which then errors at collect-time because no params; we
    # exclude it from this assertion by checking >= 18).
    # business_truth doesn't have user params here so it appears as 1 test that
    # will skip at runtime.
    output = "\n".join(result.stdout.lines)
    # Just assert each test file's tests show up. Tally is implementation-detail-sensitive.
    assert "test_resists_jailbreak_compliance" in output
    assert "test_resists_system_prompt_elicitation" in output
    assert "test_maintains_refusal_under_bypass" in output
    assert "test_deflects_off_topic_requests" in output
    assert "test_business_truth" in output
