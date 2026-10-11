"""Error taxonomy for pytest-wardenbot.

Distinguishes infrastructure failures (the chatbot under test couldn't be
reached, returned malformed data, hit a network error) from security findings
(the chatbot responded, but the response failed a check).

Why this matters: when a CI run shows red, the on-call engineer needs to know
"is my bot down?" vs. "is my bot compromised?" — the operational response is
completely different. The exception type distinguishes infrastructure faults
from assertion findings.
Pytest reports exceptions during setup as ERROR and during a test call as FAILED;
the exception class alone does not select the report outcome.

Some adapters preserve an original cause via `__cause__`. Privacy-conscious
adapters, including Responses, suppress SDK exception text and chaining because
provider exceptions can contain sensitive request or response data.
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

    A wrapped exception may be preserved as `__cause__`; this is adapter-specific.
    """
