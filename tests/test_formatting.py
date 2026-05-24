"""Tests for the shared failure-message formatter."""

from __future__ import annotations

from pytest_wardenbot._formatting import (
    DEFAULT_MAX_RESPONSE_CHARS,
    format_failure_message,
    format_indicator_list,
)


def test_format_failure_message_includes_all_required_blocks() -> None:
    msg = format_failure_message(
        kind="example failure",
        prompt="hello",
        response_text="world",
        sections=(("Indicators matched", "- pattern1\n- pattern2"),),
        remediation="do the thing",
    )
    assert "WardenBot test failed: example failure" in msg
    assert "Prompt sent:" in msg
    assert "'hello'" in msg
    assert "Indicators matched:" in msg
    assert "pattern1" in msg
    assert "Response (first 500 chars):" in msg
    assert "'world'" in msg
    assert "Agent-ready remediation" in msg
    assert "Cursor / Claude Code" in msg
    assert "do the thing" in msg


def test_format_failure_message_truncates_long_responses() -> None:
    long_text = "x" * (DEFAULT_MAX_RESPONSE_CHARS + 100)
    msg = format_failure_message(
        kind="k",
        prompt="p",
        response_text=long_text,
        remediation="r",
    )
    assert "…" in msg


def test_format_failure_message_does_not_truncate_short_responses() -> None:
    msg = format_failure_message(kind="k", prompt="p", response_text="short", remediation="r")
    assert "…" not in msg


def test_format_failure_message_respects_custom_max_chars() -> None:
    msg = format_failure_message(
        kind="k",
        prompt="p",
        response_text="ab" * 100,
        remediation="r",
        max_response_chars=10,
    )
    assert "Response (first 10 chars):" in msg
    assert "…" in msg


def test_format_failure_message_handles_no_sections() -> None:
    msg = format_failure_message(kind="k", prompt="p", response_text="resp", remediation="r")
    assert "WardenBot test failed: k" in msg
    assert "resp" in msg


def test_format_failure_message_handles_multi_line_section_bodies() -> None:
    msg = format_failure_message(
        kind="k",
        prompt="p",
        response_text="resp",
        sections=(("Multi", "line one\nline two\nline three"),),
        remediation="r",
    )
    assert "line one" in msg
    assert "line two" in msg
    assert "line three" in msg


def test_format_indicator_list_empty() -> None:
    assert format_indicator_list(()) == "(none)"


def test_format_indicator_list_shows_count_and_bullets() -> None:
    out = format_indicator_list(("pat1", "pat2"))
    assert "(2 matched)" in out
    assert "pat1" in out
    assert "pat2" in out
