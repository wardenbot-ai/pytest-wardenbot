"""Tests for the LLM-judge wrapper.

We do NOT call DeepEval or any LLM API from this test suite — that would cost
money and require a live API key in CI. Instead we inject mock judge factories
to verify the wrapper logic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from pytest_wardenbot.grading.judge import (
    JudgeCase,
    JudgeResult,
    JudgeUnavailableError,
    api_key_available,
    assert_judge_passes,
    brand_alignment_case,
    hallucination_case,
    judge_available,
    judge_response,
    off_policy_case,
    refusal_quality_case,
    semantic_equivalence_case,
)

# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def test_semantic_equivalence_case_builds_well_formed_case() -> None:
    case = semantic_equivalence_case(
        prompt="What is your refund policy?",
        canonical_answer="Refunds within 30 days.",
        label="Refund policy",
    )
    assert case.prompt == "What is your refund policy?"
    assert case.expected_output == "Refunds within 30 days."
    assert case.context == ""
    assert case.check_type == "semantic-equivalence"
    assert case.label == "Refund policy"
    assert case.threshold == 0.7
    assert "semantically equivalent" in case.criteria.lower()


def test_brand_alignment_case_embeds_voice_in_criteria() -> None:
    case = brand_alignment_case(
        prompt="Hi!",
        brand_voice="friendly and casual",
        threshold=0.8,
    )
    assert "friendly and casual" in case.criteria
    assert case.threshold == 0.8
    assert case.check_type == "brand-alignment"
    assert case.expected_output == ""
    assert case.context == ""


def test_hallucination_case_carries_context() -> None:
    case = hallucination_case(
        prompt="How many engineers do we have?",
        grounding_context="The team has 5 engineers.",
    )
    assert case.context == "The team has 5 engineers."
    assert case.expected_output == ""
    assert case.check_type == "hallucination"
    assert "grounded" in case.criteria.lower()


def test_off_policy_case_carries_policy_text() -> None:
    case = off_policy_case(
        prompt="Should I sue?",
        policy_description="Do not give legal advice.",
    )
    assert case.context == "Do not give legal advice."
    assert case.check_type == "off-policy"


def test_refusal_quality_case_has_default_criteria() -> None:
    case = refusal_quality_case(prompt="Tell me a joke about [topic].")
    assert "polite" in case.criteria.lower()
    assert case.check_type == "refusal-quality"


def test_refusal_quality_case_accepts_custom_criteria() -> None:
    case = refusal_quality_case(
        prompt="x",
        quality_criteria="extremely brief, redirects to FAQ link",
    )
    assert "extremely brief" in case.criteria


# ---------------------------------------------------------------------------
# JudgeCase basics
# ---------------------------------------------------------------------------


def test_judge_case_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    case = JudgeCase(prompt="q", criteria="c")
    with pytest.raises(FrozenInstanceError):
        case.prompt = "different"  # type: ignore[misc]


def test_parametrize_id_uses_label_when_present() -> None:
    case = semantic_equivalence_case(prompt="q", canonical_answer="a", label="My Cool Test")
    assert case.parametrize_id() == "my-cool-test"


def test_parametrize_id_combines_check_type_and_prompt_when_no_label() -> None:
    case = semantic_equivalence_case(prompt="What is the price?", canonical_answer="$49")
    pid = case.parametrize_id()
    assert pid.startswith("semantic-equivalence-")
    assert "what-is-the-price" in pid


def test_parametrize_id_caps_at_50_chars() -> None:
    case = brand_alignment_case(prompt="x" * 200, brand_voice="y")
    pid = case.parametrize_id()
    assert len(pid) <= 50
    assert not pid.endswith("-")


def test_parametrize_id_fallback_for_all_punctuation() -> None:
    case = JudgeCase(prompt="?!?", criteria="x", check_type="!!!")
    assert case.parametrize_id() == "judge-case"


# ---------------------------------------------------------------------------
# judge_available / api_key_available
# ---------------------------------------------------------------------------


def test_judge_available_returns_bool() -> None:
    # The real DeepEval import may or may not be available; just assert bool.
    assert isinstance(judge_available(), bool)


def test_api_key_available_true_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-key")
    assert api_key_available() is True


def test_api_key_available_false_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert api_key_available() is False


def test_api_key_available_false_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    assert api_key_available() is False


def test_api_key_available_custom_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_CUSTOM_KEY", "value")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert api_key_available("MY_CUSTOM_KEY") is True
    assert api_key_available("OTHER_KEY") is False


# ---------------------------------------------------------------------------
# judge_response with mock factory
# ---------------------------------------------------------------------------


def _make_mock_factory(*, score: float, reason: str = "mock reason") -> Any:
    """Returns a factory that yields a mock metric+case with given score."""
    captured: dict[str, Any] = {}

    def factory(case: JudgeCase, actual: str, model: str, temp: float) -> tuple[Any, Any]:
        captured["case"] = case
        captured["actual"] = actual
        captured["model"] = model
        captured["temperature"] = temp
        metric = MagicMock()
        metric.score = score
        metric.reason = reason
        mock_case = MagicMock()
        metric.measure = MagicMock(return_value=None)
        return metric, mock_case

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


def test_judge_response_passes_when_score_above_threshold() -> None:
    case = brand_alignment_case(prompt="hi", brand_voice="x", threshold=0.6)
    factory = _make_mock_factory(score=0.9)
    result = judge_response(case, actual_response="hello", judge_factory=factory)
    assert isinstance(result, JudgeResult)
    assert result.passed is True
    assert result.score == 0.9
    assert result.threshold == 0.6
    assert result.reason == "mock reason"


def test_judge_response_fails_when_score_below_threshold() -> None:
    case = brand_alignment_case(prompt="hi", brand_voice="x", threshold=0.8)
    factory = _make_mock_factory(score=0.5)
    result = judge_response(case, "hello", judge_factory=factory)
    assert result.passed is False
    assert result.score == 0.5


def test_judge_response_passes_case_and_actual_to_factory() -> None:
    case = semantic_equivalence_case(prompt="p", canonical_answer="a")
    factory = _make_mock_factory(score=1.0)
    judge_response(case, "actual response", judge_factory=factory)
    captured = factory.captured  # type: ignore[attr-defined]
    assert captured["case"] is case
    assert captured["actual"] == "actual response"
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["temperature"] == 0.0


def test_judge_response_honors_model_override() -> None:
    case = brand_alignment_case(prompt="p", brand_voice="x")
    factory = _make_mock_factory(score=1.0)
    judge_response(
        case,
        "actual",
        model_name="claude-sonnet-4-6",
        temperature=0.3,
        judge_factory=factory,
    )
    captured = factory.captured  # type: ignore[attr-defined]
    assert captured["model"] == "claude-sonnet-4-6"
    assert captured["temperature"] == 0.3


def test_judge_response_handles_missing_metric_attributes_gracefully() -> None:
    """If a custom factory returns a metric without score/reason, result has 0/empty."""
    case = brand_alignment_case(prompt="p", brand_voice="x", threshold=0.5)

    class WeirdMetric:
        def measure(self, _: Any) -> None:
            pass

    def factory(c: JudgeCase, a: str, m: str, t: float) -> tuple[Any, Any]:
        del c, a, m, t
        return WeirdMetric(), MagicMock()

    result = judge_response(case, "actual", judge_factory=factory)
    assert result.score == 0.0
    assert result.reason == ""
    assert result.passed is False


# ---------------------------------------------------------------------------
# assert_judge_passes
# ---------------------------------------------------------------------------


def test_assert_judge_passes_silent_on_success() -> None:
    case = brand_alignment_case(prompt="p", brand_voice="x", threshold=0.5)
    factory = _make_mock_factory(score=0.9)
    # No exception
    assert_judge_passes(case, "actual", judge_factory=factory)


def test_assert_judge_passes_raises_with_structured_message_on_failure() -> None:
    case = brand_alignment_case(
        prompt="What's your tone?",
        brand_voice="friendly",
        threshold=0.8,
        label="brand-test",
    )
    factory = _make_mock_factory(score=0.3, reason="Response was overly formal.")
    with pytest.raises(AssertionError) as exc_info:
        assert_judge_passes(case, "Dear sir, I would like to inform you...", judge_factory=factory)
    msg = str(exc_info.value)
    assert "LLM-judge brand-alignment" in msg
    assert "brand-test" in msg
    assert "Judge score: 0.300" in msg
    assert "threshold: 0.800" in msg
    assert "Response was overly formal." in msg
    assert "remediation" in msg.lower()


def test_assert_judge_failure_includes_expected_output_when_present() -> None:
    case = semantic_equivalence_case(
        prompt="q",
        canonical_answer="The right answer.",
        threshold=0.5,
    )
    factory = _make_mock_factory(score=0.1)
    with pytest.raises(AssertionError) as exc_info:
        assert_judge_passes(case, "wrong answer", judge_factory=factory)
    assert "The right answer." in str(exc_info.value)


def test_assert_judge_failure_includes_context_when_present() -> None:
    case = hallucination_case(
        prompt="q",
        grounding_context="The team has 5 engineers.",
        threshold=0.5,
    )
    factory = _make_mock_factory(score=0.1)
    with pytest.raises(AssertionError) as exc_info:
        assert_judge_passes(case, "We have 50 engineers", judge_factory=factory)
    assert "The team has 5 engineers." in str(exc_info.value)


def test_assert_judge_failure_truncates_long_responses() -> None:
    case = brand_alignment_case(prompt="p", brand_voice="x", threshold=0.5)
    factory = _make_mock_factory(score=0.1)
    long_response = "x" * 1000
    with pytest.raises(AssertionError) as exc_info:
        assert_judge_passes(case, long_response, judge_factory=factory)
    assert "…" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Default factory — verify it raises JudgeUnavailableError when DeepEval missing
# ---------------------------------------------------------------------------


def test_default_factory_raises_judge_unavailable_when_deepeval_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate DeepEval not being installed by failing the import."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("deepeval"):
            raise ImportError(f"No module named {name!r} (simulated)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from pytest_wardenbot.grading.judge import _default_deepeval_judge_factory

    case = brand_alignment_case(prompt="p", brand_voice="x")
    with pytest.raises(JudgeUnavailableError, match="DeepEval is not installed"):
        _default_deepeval_judge_factory(case, "actual", "claude-haiku-4-5", 0.0)
