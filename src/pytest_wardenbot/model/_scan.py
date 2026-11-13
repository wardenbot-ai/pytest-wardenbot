"""The credential scan: response folders get committed, so they must never hold a key.

The recorder scans every reply before writing it, and the loader scans every
file before serving it. A match is refused, naming the file and line but never
the matched text. ``allow_patterns`` in the manifest exempts false positives:
a match is allowed when one of those regular expressions finds anything in it.

An event stream is also scanned with each stream's deltas joined, because a
model echoes a key a few characters per event. The patterns with a generic
value (OpenAI keys, Bearer tokens, key parameters) skip values made only of
words, such as ``your-api-key-here`` or a URL slug, and obvious placeholders.
"""

from __future__ import annotations

import bisect
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pytest_wardenbot.model._errors import ModelEndpointError

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern))
    for kind, pattern in (
        ("an Anthropic API key", r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}"),
        ("an OpenAI API key", r"\bsk-(?:proj-|svcacct-|admin-)?(?P<value>[A-Za-z0-9_-]{20,})"),
        ("an AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        ("a Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
        ("a GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
        ("a Bearer token", r"\bBearer\s+(?P<value>[A-Za-z0-9._~+/-]{16,}=*)"),
        (
            "an api_key parameter",
            r"(?i)\bapi[_-]?key\b[\"']?\s*[=:]\s*[\"']?(?P<value>[A-Za-z0-9_-]{16,})",
        ),
        ("a key parameter", r"[?&]key=(?P<value>[A-Za-z0-9._~+/-]{16,})"),
    )
)
"""What the scan looks for, with a description of each."""

_NEWLINE = re.compile("\n")
_WORD = re.compile(r"[a-z]+|[A-Z][a-z]*|[A-Z]+|\d{1,4}")
_SEPARATORS = re.compile(r"[-_./~+=]+")
_PLACEHOLDER = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:your|example|placeholder|changeme|redacted|dummy|fake|sample|x{3,})"
    r"(?:[^a-z0-9]|$)"
)


def _not_a_secret(value: str) -> bool:
    """Words joined by separators (a slug, ``YOUR_API_KEY``) or an obvious placeholder."""
    parts = [part for part in _SEPARATORS.split(value) if part]
    return all(_WORD.fullmatch(part) for part in parts) or bool(_PLACEHOLDER.search(value))


@dataclass(frozen=True)
class Finding:
    """One credential-shaped match: where it is and what it looks like, never its text."""

    source: str
    line: int
    kind: str

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: looks like {self.kind}"


class CredentialFoundError(ModelEndpointError):
    """A response-folder file, or a reply about to be recorded, holds a credential.

    The message names the file and line and the kind of credential, never the
    matched text. Remove it, or add an ``allow_patterns`` entry to the manifest
    if it is a false positive.
    """


def scan_text(text: str, source: str, allow: Iterable[str] = ()) -> list[Finding]:
    """Every credential-shaped match in ``text`` that no allow pattern exempts."""
    allowed = [re.compile(pattern) for pattern in allow]
    newlines: list[int] | None = None
    findings: dict[int, Finding] = {}  # one per line
    for kind, pattern in CREDENTIAL_PATTERNS:
        for match in pattern.finditer(text):
            if "value" in pattern.groupindex and _not_a_secret(match.group("value")):
                continue
            if any(rule.search(match.group(0)) for rule in allowed):
                continue
            if newlines is None:
                newlines = [match.start() for match in _NEWLINE.finditer(text)]
            line = bisect.bisect_left(newlines, match.start()) + 1
            findings.setdefault(line, Finding(source, line, kind))
    return [findings[line] for line in sorted(findings)]


def scan_file(text: str, source: str, allow: Iterable[str] = ()) -> list[Finding]:
    """``scan_text``, plus an event stream's deltas joined (``.sse`` files)."""
    allow = tuple(allow)
    findings = scan_text(text, source, allow)
    if source.lower().endswith(".sse"):
        joined = joined_deltas(text)
        if joined:
            findings += scan_text(joined, f"{source} (stream deltas joined)", allow)
    return findings


def joined_deltas(text: str) -> str:
    """Each streamed text's deltas joined: Responses parts, Chat content and tool arguments."""
    groups: dict[tuple[str, ...], list[str]] = {}

    def add(key: tuple[Any, ...], value: Any) -> None:
        if isinstance(value, str):
            groups.setdefault(tuple(str(part) for part in key), []).append(value)

    for event in _sse_payloads(text):
        if not isinstance(event, Mapping):
            continue
        key = ("responses", event.get("item_id"), event.get("output_index"))
        add((*key, event.get("content_index"), event.get("type")), event.get("delta"))
        for choice in event.get("choices") or ():
            delta = choice.get("delta") if isinstance(choice, Mapping) else None
            if not isinstance(delta, Mapping):
                continue
            index = choice.get("index")
            add(("chat", index, "content"), delta.get("content"))
            add(("chat", index, "refusal"), delta.get("refusal"))
            for call in delta.get("tool_calls") or ():
                function = call.get("function") if isinstance(call, Mapping) else None
                if isinstance(function, Mapping):
                    add(("chat", index, "tool", call.get("index")), function.get("arguments"))
    return "\n".join("".join(parts) for parts in groups.values())


def _sse_payloads(text: str) -> Iterable[Any]:
    for block in text.replace("\r\n", "\n").split("\n\n"):
        data = "".join(
            line[len("data:") :].lstrip() for line in block.split("\n") if line.startswith("data:")
        )
        if data and data != "[DONE]":
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


def refuse(findings: list[Finding], *, action: str) -> None:
    """Raise ``CredentialFoundError`` if there are findings."""
    if not findings:
        return
    lines = "\n".join(f"  {finding}" for finding in findings[:10])
    more = f"\n  ... and {len(findings) - 10} more" if len(findings) > 10 else ""
    raise CredentialFoundError(
        f"Refused to {action}: it holds what looks like a credential.\n{lines}{more}\n"
        "Response folders get committed, so remove it. If it's a false positive, add a "
        "regular expression that matches it to allow_patterns in wardenbot-responses.toml. "
        "To plant a secret on purpose, use case_canary(): canary tokens never look like keys."
    )
