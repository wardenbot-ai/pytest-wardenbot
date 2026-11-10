"""Grading helpers for chatbot responses.

Two layers:

- `deterministic` — regex, substring, schema. No LLM cost.
- `judge` — LLM-as-judge via DeepEval (optional [judge] extra).
"""

from pytest_wardenbot.grading.deterministic import (
    COMPLIANCE_MARKERS,
    REFUSAL_MARKERS,
    SYSTEM_PROMPT_OVERLAP_MIN_COVERAGE,
    SYSTEM_PROMPT_OVERLAP_MIN_RUN,
    assert_maintains_refusal_under_bypass,
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
    assert_response_refuses,
    contains_any,
    contains_none,
    response_indicates_compliance,
    response_refuses,
    system_prompt_overlap,
)
from pytest_wardenbot.grading.judge import (
    JudgeCase,
    JudgeResult,
    JudgeUnavailableError,
    api_key_available,
    assert_judge_passes,
    brand_alignment_case,
    hallucination_case,
    judge_available,
    judge_response,
    off_policy_case,
    refusal_quality_case,
    semantic_equivalence_case,
)

__all__ = [
    "COMPLIANCE_MARKERS",
    "REFUSAL_MARKERS",
    "SYSTEM_PROMPT_OVERLAP_MIN_COVERAGE",
    "SYSTEM_PROMPT_OVERLAP_MIN_RUN",
    "JudgeCase",
    "JudgeResult",
    "JudgeUnavailableError",
    "api_key_available",
    "assert_judge_passes",
    "assert_maintains_refusal_under_bypass",
    "assert_no_jailbreak_compliance",
    "assert_no_system_prompt_leak",
    "assert_response_refuses",
    "brand_alignment_case",
    "contains_any",
    "contains_none",
    "hallucination_case",
    "judge_available",
    "judge_response",
    "off_policy_case",
    "refusal_quality_case",
    "response_indicates_compliance",
    "response_refuses",
    "semantic_equivalence_case",
    "system_prompt_overlap",
]
