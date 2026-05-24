"""Tests for the internal slugify helper."""

from __future__ import annotations

from pytest_wardenbot._util import slugify


def test_slugify_lowercases_and_replaces_non_alphanumeric() -> None:
    assert slugify("Hello, World!") == "hello-world"


def test_slugify_strips_leading_and_trailing_dashes() -> None:
    assert slugify("---abc---") == "abc"


def test_slugify_caps_at_max_len_and_strips_dangling_dash() -> None:
    long_text = "this-is-a-very-very-long-piece-of-text-that-should-be-capped"
    result = slugify(long_text, max_len=20)
    assert len(result) <= 20
    assert not result.endswith("-")


def test_slugify_returns_fallback_for_pure_punctuation() -> None:
    assert slugify("!!!", fallback="x") == "x"


def test_slugify_returns_fallback_for_empty_input() -> None:
    assert slugify("", fallback="default-slug") == "default-slug"


def test_slugify_collapses_repeated_separators() -> None:
    assert slugify("a__b   c--d") == "a-b-c-d"
