"""The credential scan: response folders get committed, so they must never hold a key.

The recorder scans every reply before writing it, and the loader scans every
file before serving it. A match is refused, naming the file and line but never
the matched text. ``allow_patterns`` in the manifest exempts false positives:
a match is allowed when one of those regular expressions finds anything in it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from pytest_wardenbot.model._errors import ModelEndpointError

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pattern))
    for kind, pattern in (
        ("an Anthropic API key", r"\bsk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_-]{20,}"),
        ("an OpenAI API key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}"),
        ("an AWS access key id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        ("a Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
        ("a GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})"),
        ("a Bearer token", r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*"),
        ("an api_key parameter", r"(?i)\bapi[_-]?key\b[\"']?\s*[=:]\s*[\"']?[A-Za-z0-9_-]{16,}"),
        ("a key parameter", r"[?&]key=[A-Za-z0-9._~+/-]{16,}"),
    )
)
"""What the scan looks for, with a description of each."""


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
    findings: list[Finding] = []
    for kind, pattern in CREDENTIAL_PATTERNS:
        for match in pattern.finditer(text):
            if any(rule.search(match.group(0)) for rule in allowed):
                continue
            line = text.count("\n", 0, match.start()) + 1
            finding = Finding(source, line, kind)
            if not any(f.source == source and f.line == line for f in findings):
                findings.append(finding)
    return sorted(findings, key=lambda finding: finding.line)


def refuse(findings: list[Finding], *, action: str) -> None:
    """Raise ``CredentialFoundError`` if there are findings."""
    if not findings:
        return
    lines = "\n".join(f"  {finding}" for finding in findings[:10])
    more = f"\n  ... and {len(findings) - 10} more" if len(findings) > 10 else ""
    raise CredentialFoundError(
        f"Refused to {action}: it holds what looks like a credential.\n{lines}{more}\n"
        "Response folders get committed, so remove it. If it's a false positive, add a "
        "regular expression that matches it to allow_patterns in wardenbot-responses.toml."
    )
