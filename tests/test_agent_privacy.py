"""Privacy guarantees for agent evidence serialization."""

from __future__ import annotations

import math

import pytest

from pytest_wardenbot._redaction import REDACTED_PLACEHOLDER
from pytest_wardenbot.agents._privacy import PrivacyPolicy, redact_text, safe_content


def test_redacts_longest_literal_secrets_before_truncating() -> None:
    policy = PrivacyPolicy(secrets=("token", "secret-token"), max_text_chars=15)
    assert redact_text("secret-token followed", policy=policy) == "[REDACTED] fol…"


def test_default_content_policy_hides_nonempty_values() -> None:
    policy = PrivacyPolicy()
    assert safe_content("private prompt", policy=policy) == REDACTED_PLACEHOLDER
    assert safe_content(None, policy=policy) is None
    assert safe_content("", policy=policy) == ""


def test_opted_in_content_redacts_nested_secrets_and_sensitive_fields() -> None:
    policy = PrivacyPolicy(secrets=("client-secret",), include_content=True)
    value = {"prompt": "use client-secret", "nested": [{"Authorization": "bearer"}]}
    assert safe_content(value, policy=policy) == {
        "prompt": "use [REDACTED]",
        "nested": [{"Authorization": REDACTED_PLACEHOLDER}],
    }


def test_cycles_depth_and_nonfinite_numbers_are_bounded() -> None:
    value: list[object] = []
    value.append(value)
    policy = PrivacyPolicy(include_content=True, max_depth=3)
    assert safe_content(value, policy=policy) == [REDACTED_PLACEHOLDER]
    assert safe_content(math.inf, policy=policy) == REDACTED_PLACEHOLDER
    depth_limited = safe_content(
        {"a": {"b": {"c": "deep"}}},
        policy=PrivacyPolicy(include_content=True, max_depth=2),
    )
    assert depth_limited["a"]["b"] == REDACTED_PLACEHOLDER


def test_unknown_objects_and_exception_values_are_never_rendered() -> None:
    class Dangerous:
        def __repr__(self) -> str:
            raise AssertionError("repr must not be called")

        def __str__(self) -> str:
            raise AssertionError("str must not be called")

    policy = PrivacyPolicy(include_content=True)
    assert safe_content(Dangerous(), policy=policy) == REDACTED_PLACEHOLDER
    assert safe_content(ValueError("secret detail"), policy=policy) == REDACTED_PLACEHOLDER


def test_plain_text_output_is_not_html_escaped_here() -> None:
    policy = PrivacyPolicy(include_content=True)
    assert safe_content("<script>alert(1)</script>", policy=policy) == "<script>alert(1)</script>"


@pytest.mark.parametrize("kwargs", [{"max_text_chars": -1}, {"max_depth": -1}, {"secrets": ("",)}])
def test_invalid_policy_values_raise(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PrivacyPolicy(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_text_chars": 1.5},
        {"max_text_chars": float("nan")},
        {"max_text_chars": "10"},
        {"max_text_chars": True},
        {"max_depth": 2.5},
        {"max_depth": float("nan")},
        {"max_depth": "4"},
        {"max_depth": False},
        {"include_content": 1},
        {"include_content": "yes"},
    ],
)
def test_policy_rejects_invalid_knob_types(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PrivacyPolicy(**kwargs)  # type: ignore[arg-type]
