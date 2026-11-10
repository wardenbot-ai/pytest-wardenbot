"""Redact sensitive values from chatbot response payloads.

The `raw` field on `ChatbotResponse` stores the vendor's complete API response.
If a chatbot echoes back the request's Authorization header (some debug endpoints
do this), or if the vendor's response itself contains a long-lived token, that
value would otherwise show up in pytest tracebacks and CI logs.

We do best-effort redaction: any dict key that case-insensitively contains one
of the known sensitive substrings, or names a token (`token`, `access_token`,
`refreshToken`...), has its value replaced with `[REDACTED]`. String values
anywhere in the payload also have secret-looking substrings replaced: bearer
tokens, JWTs, private key blocks and common API key formats. Lists and nested
dicts are walked recursively. Other values pass through unchanged.

This is opt-out: adapters that need the unredacted payload (debugging a vendor
response shape, for example) pass `keep_sensitive_response_fields=True`.
"""

from __future__ import annotations

import re
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
    "private_key",
    "private-key",
    "privatekey",
    "credential",
    "passwd",
    "passphrase",
)
"""Case-insensitive substrings matched against dict keys."""

# Keys that name a token, without catching usage counters such as
# "prompt_tokens" or "max_tokens".
_TOKEN_KEY = re.compile(
    r"(?:^|[_.-])(?:access|refresh|id|auth|session|bearer|api|csrf|xsrf|oauth)?[_-]?token$"
    r"|^(?:access|refresh|id|auth|session|bearer|api|csrf|xsrf|oauth)token$|^jwt$"
)

# Secret-looking substrings redacted inside any string value.
_SECRET_VALUES = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
    r"|\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"
    r"|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bxox[abposr]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}",
    re.DOTALL,
)

REDACTED_PLACEHOLDER = "[REDACTED]"


def _is_sensitive_key(key: object, sensitive_parts: tuple[str, ...]) -> bool:
    if not isinstance(key, str):
        return False
    lower = key.lower()
    return any(part in lower for part in sensitive_parts) or bool(_TOKEN_KEY.search(lower))


def redact_secret_values(text: str) -> str:
    """Replace secret-looking substrings (keys, tokens, private key blocks) in `text`."""
    return _SECRET_VALUES.sub(REDACTED_PLACEHOLDER, text)


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
    Strings: secret-looking substrings are replaced.
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
    if isinstance(payload, str):
        return redact_secret_values(payload)
    return payload
