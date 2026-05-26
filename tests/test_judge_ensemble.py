"""Tests for multi-judge ensemble grading.

The judge factory is injected, so these run with no `deepeval` install and no
paid API calls — they exercise the aggregation + ensemble wiring, not real LLMs.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any

import pytest

from pytest_wardenbot.grading.judge import (
    JudgeCase,
    _vendor_for_model,
    aggregate_verdicts,
    assert_judge_ensemble_passes,
    judge_ensemble,
)

_CASE = JudgeCase(prompt="What is your refund policy?", criteria="must be correct")


def _factory(score_by_model: dict[str, float]) -> Callable[..., tuple[Any, Any]]:
    """Build a judge_factory that returns a preset score per model name."""

    def factory(
        case: JudgeCase, actual: str, model_name: str, temperature: float
    ) -> tuple[Any, Any]:
        metric = types.SimpleNamespace(
            score=score_by_model[model_name],
            reason=f"mock judgement from {model_name}",
            measure=lambda _tc: None,
        )
        return metric, object()

    return factory


# --------------------------------------------------------------------------- #
# aggregate_verdicts
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "verdicts,policy,expected",
    [
        ([True, True, False], "majority", True),
        ([True, False, False], "majority", False),
        ([True, True], "majority", True),
        ([True, False], "majority", False),  # tie does not pass
        ([True, True, True], "unanimous", True),
        ([True, True, False], "unanimous", False),
        ([False, False, True], "any", True),
        ([False, False, False], "any", False),
    ],
)
def test_aggregate_verdicts(verdicts: list[bool], policy: str, expected: bool) -> None:
    assert aggregate_verdicts(verdicts, policy) is expected  # type: ignore[arg-type]


def test_aggregate_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        aggregate_verdicts([], "majority")


def test_aggregate_unknown_policy_raises() -> None:
    with pytest.raises(ValueError, match="Unknown consensus"):
        aggregate_verdicts([True], "supermajority")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# vendor routing
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "model_name,vendor",
    [
        ("claude-haiku-4-5", "anthropic"),
        ("anthropic.claude-3-5-sonnet", "anthropic"),
        ("gpt-4o-mini", "openai"),
        ("o1-mini", "openai"),
        ("o3", "openai"),
        ("chatgpt-4o-latest", "openai"),
        ("gemini-2.0-flash", "gemini"),
        ("some-unknown-model", "anthropic"),
    ],
)
def test_vendor_for_model(model_name: str, vendor: str) -> None:
    assert _vendor_for_model(model_name) == vendor


# --------------------------------------------------------------------------- #
# judge_ensemble
# --------------------------------------------------------------------------- #


def test_ensemble_majority_passes_two_of_three() -> None:
    models = ("claude-haiku-4-5", "gpt-4o-mini", "gemini-2.0-flash")
    factory = _factory({"claude-haiku-4-5": 0.9, "gpt-4o-mini": 0.8, "gemini-2.0-flash": 0.1})
    res = judge_ensemble(_CASE, "resp", models=models, consensus="majority", judge_factory=factory)
    assert res.passed is True
    assert res.passed_count == 2
    assert res.total == 3
    assert [m for m, _ in res.results] == list(models)  # call order preserved


def test_ensemble_unanimous_fails_on_one_dissent() -> None:
    factory = _factory({"a": 0.9, "b": 0.5})
    res = judge_ensemble(
        _CASE, "resp", models=("a", "b"), consensus="unanimous", judge_factory=factory
    )
    assert res.passed is False


def test_ensemble_any_passes_on_one() -> None:
    factory = _factory({"a": 0.1, "b": 0.8})
    res = judge_ensemble(_CASE, "resp", models=("a", "b"), consensus="any", judge_factory=factory)
    assert res.passed is True


def test_ensemble_empty_models_raises() -> None:
    with pytest.raises(ValueError, match="at least one model"):
        judge_ensemble(_CASE, "resp", models=(), judge_factory=_factory({}))


# --------------------------------------------------------------------------- #
# assert_judge_ensemble_passes
# --------------------------------------------------------------------------- #


def test_assert_passes_silently_when_consensus_met() -> None:
    factory = _factory({"a": 0.9, "b": 0.9})
    assert_judge_ensemble_passes(
        _CASE, "resp", models=("a", "b"), consensus="unanimous", judge_factory=factory
    )


def test_assert_raises_with_per_judge_breakdown() -> None:
    factory = _factory({"a": 0.9, "b": 0.1, "c": 0.1})
    with pytest.raises(AssertionError) as exc:
        assert_judge_ensemble_passes(
            _CASE, "resp", models=("a", "b", "c"), consensus="majority", judge_factory=factory
        )
    msg = str(exc.value)
    assert "1/3 judges passed" in msg
    assert "PASS  a" in msg
    assert "FAIL  b" in msg
    assert "majority" in msg


# --------------------------------------------------------------------------- #
# Consensus CLI option / fixture
# --------------------------------------------------------------------------- #


def test_judge_consensus_fixture_defaults_to_majority(wardenbot_judge_consensus: str) -> None:
    assert wardenbot_judge_consensus == "majority"
