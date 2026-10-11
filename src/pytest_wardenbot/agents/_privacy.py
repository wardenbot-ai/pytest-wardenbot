"""Bounded privacy helpers for agent evidence and report serialization.

These helpers do not make arbitrary objects safe to log. Unknown values are
omitted, and free text is hidden unless a caller explicitly opts in.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from pytest_wardenbot._redaction import DEFAULT_SENSITIVE_FIELD_PARTS, REDACTED_PLACEHOLDER

_MAX_ITEMS = 1000
_TRUNCATED = "[TRUNCATED]"


@dataclass(frozen=True)
class PrivacyPolicy:
    """Controls literal-secret filtering and optional bounded content capture."""

    secrets: tuple[str, ...] = field(default=(), repr=False)
    include_content: bool = False
    max_text_chars: int = 1000
    max_depth: int = 8

    def __post_init__(self) -> None:
        if not isinstance(self.secrets, tuple):
            raise ValueError("secrets must be a tuple")
        if any(not isinstance(secret, str) or not secret for secret in self.secrets):
            raise ValueError("secrets must contain only non-empty strings")
        if not isinstance(self.include_content, bool):
            raise ValueError("include_content must be a bool")
        if isinstance(self.max_text_chars, bool) or not isinstance(self.max_text_chars, int):
            raise ValueError("max_text_chars must be an int")
        if self.max_text_chars < 0:
            raise ValueError("max_text_chars must be >= 0")
        if isinstance(self.max_depth, bool) or not isinstance(self.max_depth, int):
            raise ValueError("max_depth must be an int")
        if self.max_depth < 0:
            raise ValueError("max_depth must be >= 0")


def redact_text(text: str, *, policy: PrivacyPolicy) -> str:
    """Replace configured literal secrets, then truncate the resulting text."""
    for secret in sorted(policy.secrets, key=len, reverse=True):
        text = text.replace(secret, REDACTED_PLACEHOLDER)
    limit = policy.max_text_chars
    if len(text) <= limit:
        return text
    if limit == 0:
        return ""
    suffix = "…"
    return text[: max(0, limit - len(suffix))] + suffix


def safe_content(value: Any, *, policy: PrivacyPolicy) -> Any:
    """Return bounded JSON-safe content, redacting by default and on ambiguity."""
    if not policy.include_content:
        if value is None:
            return None
        return "" if isinstance(value, str) and value == "" else REDACTED_PLACEHOLDER
    return _sanitize(value, policy=policy, depth=0, seen=set())


def _sanitize(value: Any, *, policy: PrivacyPolicy, depth: int, seen: set[int]) -> Any:
    if depth >= policy.max_depth and isinstance(value, dict | list | tuple):
        return REDACTED_PLACEHOLDER
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else REDACTED_PLACEHOLDER
    if isinstance(value, str):
        return redact_text(value, policy=policy)
    if not isinstance(value, dict | list | tuple):
        return REDACTED_PLACEHOLDER
    identity = id(value)
    if identity in seen:
        return REDACTED_PLACEHOLDER
    seen.add(identity)
    try:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= _MAX_ITEMS:
                    result[_TRUNCATED] = REDACTED_PLACEHOLDER
                    break
                if isinstance(key, str):
                    safe_key = redact_text(key, policy=policy)
                    sensitive_key = any(
                        part in key.lower() for part in DEFAULT_SENSITIVE_FIELD_PARTS
                    )
                else:
                    safe_key = REDACTED_PLACEHOLDER
                    sensitive_key = False
                if sensitive_key:
                    result[safe_key] = REDACTED_PLACEHOLDER
                else:
                    result[safe_key] = _sanitize(item, policy=policy, depth=depth + 1, seen=seen)
            return result
        result_list = [
            _sanitize(item, policy=policy, depth=depth + 1, seen=seen)
            for item in value[:_MAX_ITEMS]
        ]
        if len(value) > _MAX_ITEMS:
            result_list.append(_TRUNCATED)
        return result_list
    finally:
        seen.remove(identity)
