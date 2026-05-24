"""Small internal utilities shared across the plugin.

Private (leading underscore in the module name): nothing here is part of the
public API. Callers inside the package import from `pytest_wardenbot._util`;
external users should not.
"""

from __future__ import annotations

import re

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 50, fallback: str = "item") -> str:
    """Make a short, pytest-id-friendly slug from arbitrary text.

    Lowercases, replaces non-alphanumeric runs with `-`, strips leading and
    trailing `-`, and caps the length. Returns `fallback` if the result would
    be empty (e.g., input was pure punctuation).

    Used by `BusinessTruthFact.parametrize_id` and `JudgeCase.parametrize_id`
    so test IDs render consistently regardless of which type produced them.
    """
    lower = text.lower()
    slug = _SLUG_RE.sub("-", lower).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or fallback
