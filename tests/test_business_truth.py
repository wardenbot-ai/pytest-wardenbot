"""Tests for the business-truth assertion helpers."""

from __future__ import annotations

import pytest

from pytest_wardenbot.business_truth import (
    BusinessTruthFact,
    assert_truth_fact_match,
)

# ---------------------------------------------------------------------------
# BusinessTruthFact basics
# ---------------------------------------------------------------------------


def test_fact_is_frozen() -> None:
    from dataclasses import FrozenInstanceError

    fact = BusinessTruthFact(question="q", expected_answer="a")
    with pytest.raises(FrozenInstanceError):
        fact.question = "different"  # type: ignore[misc]


def test_fact_default_match_type_is_substring() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="a")
    assert fact.match_type == "substring"


def test_fact_parametrize_id_from_label() -> None:
    fact = BusinessTruthFact(
        question="Long winded question about pricing details?",
        expected_answer="$49",
        label="Standard plan price",
    )
    assert fact.parametrize_id() == "standard-plan-price"


def test_fact_parametrize_id_from_question_when_no_label() -> None:
    fact = BusinessTruthFact(question="What is the price?", expected_answer="$49")
    assert fact.parametrize_id() == "what-is-the-price"


def test_fact_parametrize_id_caps_at_40_chars() -> None:
    fact = BusinessTruthFact(
        question="What is the price of the deluxe gold plated unicorn package?",
        expected_answer="$1000",
    )
    pid = fact.parametrize_id()
    assert len(pid) <= 40
    assert not pid.endswith("-")


def test_fact_parametrize_id_fallback_for_all_punctuation() -> None:
    fact = BusinessTruthFact(question="!?!", expected_answer="x")
    assert fact.parametrize_id() == "fact"


# ---------------------------------------------------------------------------
# substring matching
# ---------------------------------------------------------------------------


def test_substring_match_passes_when_expected_in_response() -> None:
    fact = BusinessTruthFact(
        question="How much does it cost?",
        expected_answer="$49",
        match_type="substring",
    )
    assert_truth_fact_match("Our plan is $49/month.", fact)


def test_substring_match_case_insensitive() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="ACME Corp")
    assert_truth_fact_match("welcome to acme corp", fact)


def test_substring_match_accepts_variations() -> None:
    fact = BusinessTruthFact(
        question="How much?",
        expected_answer="$49",
        acceptable_variations=("forty-nine dollars", "49 USD"),
    )
    assert_truth_fact_match("That'll be forty-nine dollars.", fact)


def test_substring_match_fails_when_absent() -> None:
    fact = BusinessTruthFact(
        question="How much does it cost?",
        expected_answer="$49",
        label="Standard plan price",
    )
    with pytest.raises(AssertionError) as exc_info:
        assert_truth_fact_match("Our plan is $999/month.", fact)
    msg = str(exc_info.value)
    assert "business-truth mismatch" in msg
    assert "Standard plan price" in msg
    assert "$49" in msg


# ---------------------------------------------------------------------------
# exact matching
# ---------------------------------------------------------------------------


def test_exact_match_passes_with_whitespace_trim() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="yes", match_type="exact")
    assert_truth_fact_match("  Yes  ", fact)


def test_exact_match_fails_when_response_has_extra_text() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="yes", match_type="exact")
    with pytest.raises(AssertionError):
        assert_truth_fact_match("Yes, absolutely.", fact)


# ---------------------------------------------------------------------------
# numeric_range matching
# ---------------------------------------------------------------------------


def test_numeric_range_passes_when_in_range() -> None:
    fact = BusinessTruthFact(
        question="How much?",
        expected_answer="around 49",
        match_type="numeric_range",
        numeric_range=(40.0, 60.0),
    )
    assert_truth_fact_match("It costs around $49 per month.", fact)


def test_numeric_range_handles_commas_and_decimals() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer="x",
        match_type="numeric_range",
        numeric_range=(1000.0, 10000.0),
    )
    assert_truth_fact_match("We had 1,234.56 customers last year.", fact)


def test_numeric_range_fails_when_outside() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer="x",
        match_type="numeric_range",
        numeric_range=(40.0, 60.0),
    )
    with pytest.raises(AssertionError):
        assert_truth_fact_match("It costs $999 per month.", fact)


def test_numeric_range_fails_when_no_numbers_at_all() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer="x",
        match_type="numeric_range",
        numeric_range=(1.0, 100.0),
    )
    with pytest.raises(AssertionError):
        assert_truth_fact_match("We are open during business hours.", fact)


def test_numeric_range_raises_without_range_configured() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="x", match_type="numeric_range")
    with pytest.raises(ValueError, match="numeric_range"):
        assert_truth_fact_match("text with 42 in it", fact)


def test_numeric_range_raises_on_inverted_range() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer="x",
        match_type="numeric_range",
        numeric_range=(100.0, 1.0),
    )
    with pytest.raises(ValueError, match=r"min.*max"):
        assert_truth_fact_match("text with 42", fact)


# ---------------------------------------------------------------------------
# regex matching
# ---------------------------------------------------------------------------


def test_regex_match_passes() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer=r"\$\d+(?:\.\d{2})?",
        match_type="regex",
    )
    assert_truth_fact_match("Pricing starts at $49.99 per month.", fact)


def test_regex_match_fails() -> None:
    fact = BusinessTruthFact(
        question="q",
        expected_answer=r"\$\d+",
        match_type="regex",
    )
    with pytest.raises(AssertionError):
        assert_truth_fact_match("Pricing is free.", fact)


# ---------------------------------------------------------------------------
# Failure message structure
# ---------------------------------------------------------------------------


def test_failure_message_includes_remediation() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="$49", label="price")
    with pytest.raises(AssertionError) as exc_info:
        assert_truth_fact_match("we cost a lot", fact)
    msg = str(exc_info.value)
    assert "remediation" in msg.lower()
    assert "Cursor / Claude Code" in msg
    assert "price" in msg


def test_failure_message_truncates_long_responses() -> None:
    fact = BusinessTruthFact(question="q", expected_answer="$49")
    long_text = "wrong " * 200
    with pytest.raises(AssertionError) as exc_info:
        assert_truth_fact_match(long_text, fact)
    assert "…" in str(exc_info.value)
