"""LLM-judge tests (optional [judge] extra).

Parametrized over a user-supplied list of `JudgeCase` entries. Asks the chatbot
each case's prompt, then asks a judge LLM (Anthropic Haiku 4.5 by default) to
score the response against the case's criteria. Pass if score >= threshold.

Skip behavior:
- `[judge]` extra not installed -> skipped with install instructions
- API key (ANTHROPIC_API_KEY) not set -> skipped with the env-var name
- `judge_case` fixture not configured -> skipped with onboarding template

Note: this module accesses the judge helpers via the module (not via `from
... import ...`) so users (and our own pytester tests) can patch them via
`monkeypatch.setattr(judge_module, ...)`.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading import judge as judge_module
from pytest_wardenbot.grading.judge import JudgeCase


@pytest.mark.wardenbot
@pytest.mark.severity_medium
def test_semantic(chatbot: ChatbotAdapter, judge_case: JudgeCase) -> None:
    """Send the case's prompt; assert the judge passes against its rubric."""
    if not judge_module.judge_available():
        pytest.skip("DeepEval not installed. Install with: pip install 'pytest-wardenbot[judge]'")
    if not judge_module.api_key_available():
        pytest.skip(
            "ANTHROPIC_API_KEY not set. LLM-judge tests need an API key — "
            "the default judge model is Anthropic Haiku 4.5 (~$0.003 per case)."
        )

    response = chatbot.send_message(judge_case.prompt)

    try:
        judge_module.assert_judge_passes(judge_case, response.text)
    except judge_module.JudgeUnavailableError as exc:
        pytest.skip(str(exc))
