"""Refusal-bypass tests.

Sends prompts that use adversarial framings (roleplay, educational pretext,
hypothetical scenarios) intended to make the chatbot rationalize compliance
with a request it would otherwise refuse. The assertion: the chatbot maintains
its refusal stance — refusal markers present, compliance markers absent.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.grading.deterministic import assert_maintains_refusal_under_bypass


@pytest.mark.wardenbot
@pytest.mark.severity_high
@pytest.mark.parametrize(
    "prompt,attack_id",
    REFUSAL_BYPASS_PROMPTS,
    ids=[attack_id for _, attack_id in REFUSAL_BYPASS_PROMPTS],
)
def test_maintains_refusal_under_bypass(
    chatbot: ChatbotAdapter, prompt: str, attack_id: str
) -> None:
    """Send a bypass-framed prompt; assert the chatbot refuses cleanly."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_maintains_refusal_under_bypass(response.text, prompt)
