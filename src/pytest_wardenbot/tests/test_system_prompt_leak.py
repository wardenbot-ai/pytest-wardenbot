"""System-prompt leak elicitation tests.

Sends prompts designed to extract the chatbot's hidden system prompt and
verifies the response does not show signs of leakage.

Distinct from `test_prompt_injection.py`: those tests use broader jailbreak
patterns that *might* lead to leakage. These prompts are purpose-built
extraction attempts.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS
from pytest_wardenbot.grading.deterministic import assert_no_system_prompt_leak


@pytest.mark.wardenbot
@pytest.mark.severity_high
@pytest.mark.parametrize(
    "prompt,attack_id",
    SYSTEM_PROMPT_LEAK_PROMPTS,
    ids=[attack_id for _, attack_id in SYSTEM_PROMPT_LEAK_PROMPTS],
)
def test_resists_system_prompt_elicitation(
    chatbot: ChatbotAdapter, prompt: str, attack_id: str
) -> None:
    """Send a targeted system-prompt-extraction prompt; assert no leak."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_no_system_prompt_leak(response.text, prompt)
