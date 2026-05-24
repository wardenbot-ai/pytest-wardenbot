"""Agent-ready Markdown remediation formatter.

When a wardenbot test fails, we want the failure message to include a block
that a developer can paste directly into Cursor / Claude Code / Cody / etc.
The agent should have everything it needs to investigate and fix the issue
without further back-and-forth.

This is the v0.1 shape — minimal but complete. v0.2 will expand to include
suggested file/component locations once we learn from real customer reports.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Remediation:
    """A structured remediation note attached to a failing test."""

    title: str
    """Short title, e.g. 'Strengthen jailbreak refusal'."""

    why_it_matters: str
    """One paragraph explaining the failure mode to a non-security engineer."""

    investigate: tuple[str, ...]
    """Concrete things to check, in order."""

    fix_suggestions: tuple[str, ...]
    """Concrete things to try, in order of usual effectiveness."""

    def to_agent_markdown(self) -> str:
        """Render as agent-ready Markdown.

        Format chosen to work well as a paste into Claude Code / Cursor / Cody.
        First-person prompt; gives the agent a clear task.
        """
        investigate = "\n".join(f"- {item}" for item in self.investigate)
        fix_suggestions = "\n".join(f"- {item}" for item in self.fix_suggestions)

        return f"""# Task: {self.title}

## Why this matters

{self.why_it_matters}

## Investigate

{investigate}

## Suggested fixes

{fix_suggestions}

## Acceptance criteria

After your fix, re-run `pytest` against the same chatbot endpoint. The failing
wardenbot test must pass. No new wardenbot tests should regress.
"""
