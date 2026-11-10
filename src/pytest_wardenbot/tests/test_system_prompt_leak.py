"""System-prompt leak elicitation tests.

Sends prompts designed to extract the chatbot's hidden system prompt and
verifies the response does not leak it. With a canary (`wardenbot_canary`,
or the `WARDENBOT_CANARY` environment variable) or the known prompt text
(`wardenbot_system_prompt`), leaked content is detected directly. Without
either, only disclosure phrasing is checked and an unframed verbatim dump
passes.

Distinct from `test_prompt_injection.py`: those tests use broader jailbreak
patterns that *might* lead to leakage. These prompts are purpose-built
extraction attempts.

Corpus comes from the `wardenbot_system_prompt_leak_prompts` fixture, which
defaults to the bundled `SYSTEM_PROMPT_LEAK_PROMPTS`. Override in your
conftest.py to substitute or extend.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading.deterministic import assert_no_system_prompt_leak


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_resists_system_prompt_elicitation(
    chatbot: ChatbotAdapter,
    prompt: str,
    attack_id: str,
    wardenbot_canary: str | None,
    wardenbot_system_prompt: str | None,
) -> None:
    """Send a targeted system-prompt-extraction prompt; assert no leak."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_no_system_prompt_leak(
        response.text, prompt, system_prompt=wardenbot_system_prompt, canary=wardenbot_canary
    )
