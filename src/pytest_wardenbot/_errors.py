"""Error taxonomy for pytest-wardenbot.

Distinguishes infrastructure failures (the chatbot under test couldn't be
reached, returned malformed data, hit a network error) from security findings
(the chatbot responded, but the response failed a check).

Why this matters: when a CI run shows red, the on-call engineer needs to know
"is my bot down?" vs. "is my bot compromised?" — the operational response is
completely different. `WardenBotInfraError` propagating naturally lands the
result in pytest's ERROR bucket (vs. FAILURE for assertions), so the
distinction is visible without any custom reporting layer.

Callers that need the original cause can access it via `__cause__` since all
wrappers use `raise ... from exc`.
"""

from __future__ import annotations


class WardenBotError(Exception):
    """Base class for all pytest-wardenbot exceptions."""


class WardenBotInfraError(WardenBotError):
    """The chatbot under test could not be reached or returned malformed data.

    Raised by adapters when the underlying transport fails (network error,
    HTTP 5xx, timeout), or the response is structurally wrong (non-JSON,
    missing expected field, wrong type). Distinct from AssertionError, which
    signals the chatbot DID respond but failed a security check.

    The original exception is preserved as `__cause__`.
    """
