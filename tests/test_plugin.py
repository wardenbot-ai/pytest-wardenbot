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
# Shipped LLM-judge (test_semantic) skip / pass / fail paths
# ---------------------------------------------------------------------------


def test_shipped_judge_test_skips_without_judge_case_fixture(
    pytester: pytest.Pytester,
) -> None:
    """No `judge_case` fixture configured → skip with helpful message."""
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_semantic", "-v", "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*No `judge_case` fixture configured*"])


_JUDGE_FIXTURE_HEADER = """
import pytest
from unittest.mock import MagicMock
from pytest_wardenbot.adapters.base import ChatbotResponse
from pytest_wardenbot.grading import judge as judge_module
from pytest_wardenbot.grading.judge import brand_alignment_case

class SafeBot:
    name = "safe-bot"
    def send_message(self, prompt, *, session_id=None):
        return ChatbotResponse(text="Friendly hello!", raw={})
    def reset_session(self, session_id):
        pass

@pytest.fixture
def chatbot():
    return SafeBot()

@pytest.fixture(params=[
    brand_alignment_case(prompt="say hi", brand_voice="friendly", threshold=0.5),
], ids=lambda c: c.parametrize_id())
def judge_case(request):
    return request.param
"""


def test_shipped_judge_test_skips_when_deepeval_missing(
    pytester: pytest.Pytester,
) -> None:
    """DeepEval not installed -> skip with install instructions."""
    pytester.makeconftest(
        _JUDGE_FIXTURE_HEADER
        + """
@pytest.fixture(autouse=True)
def _patch_unavailable(monkeypatch):
    monkeypatch.setattr(judge_module, "judge_available", lambda: False)
"""
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_semantic", "-v", "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*DeepEval not installed*"])


def test_shipped_judge_test_skips_when_api_key_missing(
    pytester: pytest.Pytester,
) -> None:
    """DeepEval installed but API key missing -> skip with env-var note."""
    pytester.makeconftest(
        _JUDGE_FIXTURE_HEADER
        + """
@pytest.fixture(autouse=True)
def _patch_no_api_key(monkeypatch):
    monkeypatch.setattr(judge_module, "judge_available", lambda: True)
    monkeypatch.setattr(
        judge_module,
        "api_key_available",
        lambda env_var="ANTHROPIC_API_KEY": False,
    )
"""
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_semantic", "-v", "-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*ANTHROPIC_API_KEY not set*"])


def test_shipped_judge_test_passes_with_mocked_factory(
    pytester: pytest.Pytester,
) -> None:
    """Available + key set + judge returns high score -> test passes."""
    pytester.makeconftest(
        _JUDGE_FIXTURE_HEADER
        + """
@pytest.fixture(autouse=True)
def _patch_passing_judge(monkeypatch):
    monkeypatch.setattr(judge_module, "judge_available", lambda: True)
    monkeypatch.setattr(
        judge_module,
        "api_key_available",
        lambda env_var="ANTHROPIC_API_KEY": True,
    )
    def passing_factory(case, actual, model, temp):
        metric = MagicMock()
        metric.score = 0.95
        metric.reason = "great alignment"
        metric.measure = MagicMock()
        return metric, MagicMock()
    monkeypatch.setattr(
        judge_module, "_default_deepeval_judge_factory", passing_factory
    )
"""
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_semantic", "-v")
    result.assert_outcomes(passed=1)


def test_shipped_judge_test_fails_with_failing_mocked_factory(
    pytester: pytest.Pytester,
) -> None:
    """Available + key set + judge returns low score -> test fails."""
    pytester.makeconftest(
        _JUDGE_FIXTURE_HEADER
        + """
@pytest.fixture(autouse=True)
def _patch_failing_judge(monkeypatch):
    monkeypatch.setattr(judge_module, "judge_available", lambda: True)
    monkeypatch.setattr(
        judge_module,
        "api_key_available",
        lambda env_var="ANTHROPIC_API_KEY": True,
    )
    def failing_factory(case, actual, model, temp):
        metric = MagicMock()
        metric.score = 0.2
        metric.reason = "tone mismatch"
        metric.measure = MagicMock()
        return metric, MagicMock()
    monkeypatch.setattr(
        judge_module, "_default_deepeval_judge_factory", failing_factory
    )
"""
    )
    result = pytester.runpytest("--pyargs", "pytest_wardenbot.tests.test_semantic", "-v")
    result.assert_outcomes(failed=1)


# ---------------------------------------------------------------------------
# Discovery: full shipped test set is collectable as one --pyargs run
# ---------------------------------------------------------------------------


def test_all_shipped_tests_discoverable(pytester: pytest.Pytester) -> None:
    """`pytest --co --pyargs pytest_wardenbot.tests` discovers all shipped tests."""
    pytester.makeconftest(_SAFE_BOT_CONFTEST)
    result = pytester.runpytest("--co", "-q", "--pyargs", "pytest_wardenbot.tests")
    output = "\n".join(result.stdout.lines)
    # Each test function name appears in the collection output.
    assert "test_resists_jailbreak_compliance" in output
    assert "test_resists_system_prompt_elicitation" in output
    assert "test_maintains_refusal_under_bypass" in output
    assert "test_deflects_off_topic_requests" in output
    assert "test_business_truth" in output
    assert "test_semantic" in output
