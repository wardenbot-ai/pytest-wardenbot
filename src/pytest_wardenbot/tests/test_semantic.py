"""LLM-judge tests (optional [judge] extra).

Parametrized over a user-supplied list of `JudgeCase` entries. Asks the chatbot
each case's prompt, then asks a judge LLM (Anthropic Haiku 4.5 by default) to
score the response against the case's criteria. Pass if score >= threshold.

When the judge cannot run:
- `judge_case` fixture not configured -> skipped with an onboarding template
- `[judge]` extra not installed, or the judge's API key (ANTHROPIC_API_KEY for
  the default model) not set -> FAILS, because judge cases are configured and a
  run that silently skips them would look green. Pass
  `--wardenbot-judge-optional` to skip instead (for example on fork pull
  requests that have no secrets).

Note: this module accesses the judge helpers via the module (not via `from
... import ...`) so users (and our own pytester tests) can patch them via
`monkeypatch.setattr(judge_module, ...)`.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading import judge as judge_module
from pytest_wardenbot.grading.judge import JudgeCase

_OPTIONAL_HINT = (
    " Judge cases are configured, so this fails instead of skipping. Pass "
    "--wardenbot-judge-optional to skip judge tests when the judge cannot run "
    "(for example on fork pull requests without secrets)."
)


@pytest.mark.wardenbot
@pytest.mark.severity_medium
def test_semantic(
    chatbot: ChatbotAdapter, judge_case: JudgeCase, request: pytest.FixtureRequest
) -> None:
    """Send the case's prompt; assert the judge passes against its rubric."""
    optional = bool(request.config.getoption("wardenbot_judge_optional", default=False))

    def unavailable(message: str) -> None:
        if optional:
            pytest.skip(message)
        pytest.fail(message + _OPTIONAL_HINT, pytrace=False)

    if not judge_module.judge_available():
        unavailable("DeepEval not installed. Install with: pip install 'pytest-wardenbot[judge]'.")
    # Called without arguments so stubs written for earlier releases keep working;
    # the default checks the default judge model's key.
    if not judge_module.api_key_available():
        key = judge_module.judge_key_env()
        unavailable(
            f"{key} not set. LLM-judge tests need an API key; the default judge model is "
            "Anthropic Haiku 4.5 (~$0.003 per case)."
        )

    response = chatbot.send_message(judge_case.prompt)

    try:
        judge_module.assert_judge_passes(judge_case, response.text)
    except judge_module.JudgeUnavailableError as exc:
        unavailable(str(exc))
