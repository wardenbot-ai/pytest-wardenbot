"""Grading helpers for chatbot responses.

Three layers, per the WardenBot AI doctrine (script-first / LLM-fallback / human-sample):

- `deterministic` — regex, substring, schema. No LLM cost. v0.1.
- `judge` — LLM-as-judge via DeepEval. Optional [judge] extra. v0.1.
- `human_sample` — weekly calibration loop. v0.3+, requires managed backend.
"""

from pytest_wardenbot.grading.deterministic import (
    COMPLIANCE_MARKERS,
    REFUSAL_MARKERS,
    assert_maintains_refusal_under_bypass,
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
    assert_response_refuses,
    contains_any,
    contains_none,
    response_indicates_compliance,
    response_refuses,
)

__all__ = [
    "COMPLIANCE_MARKERS",
    "REFUSAL_MARKERS",
    "assert_maintains_refusal_under_bypass",
    "assert_no_jailbreak_compliance",
    "assert_no_system_prompt_leak",
    "assert_response_refuses",
    "contains_any",
    "contains_none",
    "response_indicates_compliance",
    "response_refuses",
]
