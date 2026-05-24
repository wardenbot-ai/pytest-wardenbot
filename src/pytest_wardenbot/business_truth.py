"""Business-truth assertion helpers.

Customers tell the chatbot facts about their business (pricing, hours, refund
policy, contact info, services offered). Those facts should stay correct over
time — a model update should not start telling people the wrong price.

A `BusinessTruthFact` captures one such fact + how to verify it. The shipped
`test_business_truth.py` test is parametrized over a user-supplied list of
facts (via the `business_truth_fact` fixture, which users override in their
own conftest.py).

Supports four match types:

- `exact`   — response must equal `expected_answer` (case-insensitive trim).
- `substring` — response must contain `expected_answer` (or any acceptable variation).
- `numeric_range` — response must contain a number in `numeric_range`.
- `regex`   — response must match `expected_answer` as a regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

MatchType = Literal["exact", "substring", "numeric_range", "regex"]


@dataclass(frozen=True)
class BusinessTruthFact:
    """A single fact the chatbot should always answer correctly.

    Example:
        BusinessTruthFact(
            label="Standard plan price",
            question="How much does the Standard plan cost per month?",
            expected_answer="$49",
            match_type="substring",
            acceptable_variations=("$49/mo", "49 dollars", "forty-nine dollars"),
        )
    """

    question: str
    """The prompt to send the chatbot."""

    expected_answer: str
    """The expected answer (or pattern, depending on `match_type`)."""

    match_type: MatchType = "substring"
    """How to compare the response to the expected answer."""

    label: str = ""
    """Optional short label used as the parametrize ID. Defaults to a slug of `question`."""

    acceptable_variations: tuple[str, ...] = field(default_factory=tuple)
    """Alternative phrasings that should also pass (for `substring` match)."""

    numeric_range: tuple[float, float] | None = None
    """Inclusive (min, max) range for `numeric_range` match."""

    def parametrize_id(self) -> str:
        """The string shown as the parametrize ID in pytest output."""
        if self.label:
            return _slugify(self.label)
        return _slugify(self.question)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def assert_truth_fact_match(response_text: str, fact: BusinessTruthFact) -> None:
    """Assert the chatbot's response correctly answers `fact`.

    Raises AssertionError with a structured message including:
    - The fact label + question
    - The expected answer + match type
    - The actual (truncated) response
    - An agent-ready remediation block
    """
    matcher = _MATCHERS[fact.match_type]
    if matcher(response_text, fact):
        return

    raise AssertionError(_format_truth_failure(response_text, fact))


def _match_exact(response_text: str, fact: BusinessTruthFact) -> bool:
    return response_text.strip().casefold() == fact.expected_answer.strip().casefold()


def _match_substring(response_text: str, fact: BusinessTruthFact) -> bool:
    haystack = response_text.casefold()
    candidates = (fact.expected_answer, *fact.acceptable_variations)
    return any(c.casefold() in haystack for c in candidates if c)


def _match_numeric_range(response_text: str, fact: BusinessTruthFact) -> bool:
    if fact.numeric_range is None:
        raise ValueError(
            f"BusinessTruthFact {fact.label or fact.question!r} has match_type='numeric_range' "
            "but no numeric_range=(min, max) was provided."
        )
    lo, hi = fact.numeric_range
    if lo > hi:
        raise ValueError(
            f"BusinessTruthFact {fact.label or fact.question!r} has numeric_range "
            f"min ({lo}) > max ({hi})."
        )
    # Find all numeric tokens in the response, including decimals + commas.
    matches = re.findall(r"-?\d{1,3}(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", response_text)
    for raw in matches:
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if lo <= value <= hi:
            return True
    return False


def _match_regex(response_text: str, fact: BusinessTruthFact) -> bool:
    return re.search(fact.expected_answer, response_text) is not None


_MATCHERS = {
    "exact": _match_exact,
    "substring": _match_substring,
    "numeric_range": _match_numeric_range,
    "regex": _match_regex,
}


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_truth_failure(response_text: str, fact: BusinessTruthFact) -> str:
    truncated = response_text if len(response_text) <= 500 else response_text[:500] + "…"
    label = fact.label or "(unlabeled fact)"

    if fact.match_type == "numeric_range" and fact.numeric_range is not None:
        expected_desc = f"a number in range [{fact.numeric_range[0]}, {fact.numeric_range[1]}]"
    elif fact.match_type == "substring" and fact.acceptable_variations:
        expected_desc = (
            f"{fact.expected_answer!r} (or any of: "
            f"{', '.join(repr(v) for v in fact.acceptable_variations)})"
        )
    else:
        expected_desc = repr(fact.expected_answer)

    return (
        f"WardenBot test failed: business-truth mismatch\n"
        f"\n"
        f"  Fact: {label}\n"
        f"  Question asked:\n"
        f"    {fact.question!r}\n"
        f"\n"
        f"  Expected ({fact.match_type}):\n"
        f"    {expected_desc}\n"
        f"\n"
        f"  Actual response (first 500 chars):\n"
        f"    {truncated!r}\n"
        f"\n"
        f"  Agent-ready remediation (paste into Cursor / Claude Code):\n"
        f"    Your chatbot answered a business-truth question incorrectly. "
        f"This usually means: (1) the fact is missing from its system prompt or "
        f"RAG corpus, (2) the model is hallucinating because the fact is not "
        f"prominent enough, or (3) the upstream model was updated and behavior "
        f"changed. Add the fact explicitly to your knowledge base and re-run "
        f"this test against the same chatbot to confirm the fix.\n"
    )


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Make a short, pytest-id-friendly slug from arbitrary text."""
    lower = text.lower()
    slug = _SLUG_RE.sub("-", lower).strip("-")
    # Cap at 40 chars to keep test IDs readable.
    if len(slug) > 40:
        slug = slug[:40].rstrip("-")
    return slug or "fact"
