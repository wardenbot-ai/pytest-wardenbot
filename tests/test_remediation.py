"""Tests for the agent-ready Markdown remediation formatter."""

from __future__ import annotations

from pytest_wardenbot.remediation import Remediation


def test_remediation_renders_all_sections() -> None:
    rem = Remediation(
        title="Strengthen jailbreak refusal",
        why_it_matters="Customers can extract internal instructions.",
        investigate=(
            "Look at the system prompt.",
            "Check for outbound response filters.",
        ),
        fix_suggestions=(
            "Add explicit deny instruction.",
            "Add outbound filter.",
        ),
    )
    md = rem.to_agent_markdown()
    assert "# Task: Strengthen jailbreak refusal" in md
    assert "## Why this matters" in md
    assert "Customers can extract internal instructions." in md
    assert "- Look at the system prompt." in md
    assert "- Check for outbound response filters." in md
    assert "- Add explicit deny instruction." in md
    assert "- Add outbound filter." in md
    assert "## Acceptance criteria" in md


def test_remediation_handles_empty_lists() -> None:
    rem = Remediation(
        title="t",
        why_it_matters="w",
        investigate=(),
        fix_suggestions=(),
    )
    md = rem.to_agent_markdown()
    assert "## Investigate" in md
    assert "## Suggested fixes" in md
