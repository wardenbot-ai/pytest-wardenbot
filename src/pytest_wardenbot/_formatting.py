"""Shared failure-message formatting.

All shipped tests produce assertion messages with the same skeleton:

    WardenBot test failed: <kind>

      Prompt sent:
        <prompt>

      <one or more labeled sections>

      Response (first N chars):
        <truncated response>

      Agent-ready remediation (paste into Cursor / Claude Code):
        <remediation>

Keeping the format in one place means: (a) the agent-ready remediation block
renders identically across deterministic / business-truth / judge / future
runner failures, so downstream tooling can parse it consistently, and (b)
adjusting the truncation cap or layout is one edit, not three.
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_MAX_RESPONSE_CHARS = 500
"""Cap response text in failure messages. Prevents PII-bearing bot replies
from dumping megabytes into CI logs."""


def format_failure_message(
    *,
    kind: str,
    prompt: str,
    response_text: str,
    sections: Sequence[tuple[str, str]] = (),
    remediation: str,
    max_response_chars: int = DEFAULT_MAX_RESPONSE_CHARS,
) -> str:
    """Render a structured WardenBot failure message.

    Args:
        kind: Short category, e.g. "jailbreak compliance" or "business-truth mismatch".
        prompt: The prompt that was sent to the chatbot.
        response_text: The chatbot's response. Truncated to `max_response_chars`.
        sections: Optional extra labeled blocks rendered between prompt and response.
            Each entry is `(label, body)`. Body may contain newlines; it's indented
            uniformly under the label.
        remediation: Agent-ready prose pasted into the trailing remediation block.
        max_response_chars: Cap on response text. Default 500.
    """
    truncated = (
        response_text
        if len(response_text) <= max_response_chars
        else response_text[:max_response_chars] + "…"
    )

    parts: list[str] = [
        f"WardenBot test failed: {kind}",
        "",
        "  Prompt sent:",
        f"    {prompt!r}",
        "",
    ]

    for label, body in sections:
        parts.append(f"  {label}:")
        for line in body.splitlines() or [""]:
            parts.append(f"    {line}")
        parts.append("")

    parts.extend(
        [
            f"  Response (first {max_response_chars} chars):",
            f"    {truncated!r}",
            "",
            "  Agent-ready remediation (paste into Cursor / Claude Code):",
            f"    {remediation}",
            "",
        ]
    )

    return "\n".join(parts)


def format_indicator_list(indicators: Sequence[str]) -> str:
    """Render an indicator list as a multi-line section body.

    Used by deterministic checks where the section is "which patterns matched".
    """
    if not indicators:
        return "(none)"
    lines = [f"({len(indicators)} matched)"]
    lines.extend(f"  - {ind}" for ind in indicators)
    return "\n".join(lines)
