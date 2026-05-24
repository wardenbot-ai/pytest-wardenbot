"""Redact sensitive values from chatbot response payloads.

The `raw` field on `ChatbotResponse` stores the vendor's complete API response.
If a chatbot echoes back the request's Authorization header (some debug endpoints
do this), or if the vendor's response itself contains a long-lived token, that
value would otherwise show up in pytest tracebacks and CI logs.

We do best-effort redaction: any dict key that case-insensitively contains one
of the known sensitive substrings has its value replaced with `[REDACTED]`.
Lists and nested dicts are walked recursively. Non-dict / non-list values pass
through unchanged.

This is opt-out: adapters that need the unredacted payload (debugging a vendor
response shape, for example) pass `keep_sensitive_response_fields=True`.
"""

from __future__ import annotations

from typing import Any

DEFAULT_SENSITIVE_FIELD_PARTS: tuple[str, ...] = (
    "authorization",
    "auth-token",
    "auth_token",
    "api-key",
    "api_key",
    "apikey",
    "cookie",
    "set-cookie",
    "password",
    "secret",
    "bearer",
    "x-token",
    "x_token",
    "session-token",
    "session_token",
)
"""Case-insensitive substrings matched against dict keys."""

REDACTED_PLACEHOLDER = "[REDACTED]"


def _is_sensitive_key(key: object, sensitive_parts: tuple[str, ...]) -> bool:
    if not isinstance(key, str):
        return False
    lower = key.lower()
    return any(part in lower for part in sensitive_parts)


def redact_response_payload(
    payload: Any,
    *,
    sensitive_parts: tuple[str, ...] = DEFAULT_SENSITIVE_FIELD_PARTS,
) -> Any:
    """Return a deep copy of `payload` with sensitive values redacted.

    Dicts: any value whose key contains a sensitive substring is replaced
    with `REDACTED_PLACEHOLDER`. All other values are walked recursively.
    Lists, tuples: each element is walked recursively (tuples become lists
    since they aren't JSON-native).
    Other types: returned unchanged.

    Returns the input unchanged if not a dict/list/tuple — adapters can pass
    arbitrary payloads without checking the type first.
    """
    if isinstance(payload, dict):
        return {
            k: (
                REDACTED_PLACEHOLDER
                if _is_sensitive_key(k, sensitive_parts)
                else redact_response_payload(v, sensitive_parts=sensitive_parts)
            )
            for k, v in payload.items()
        }
    if isinstance(payload, list | tuple):
        return [redact_response_payload(item, sensitive_parts=sensitive_parts) for item in payload]
    return payload
