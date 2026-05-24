"""Prompt injection / jailbreak resistance tests.

Each test in this file sends a known jailbreak prompt to the chatbot under test
and asserts the response does not show explicit signs of compliance.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.grading.deterministic import (
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
)


@pytest.mark.wardenbot
@pytest.mark.severity_high
@pytest.mark.parametrize(
    "prompt,attack_id",
    JAILBREAK_PROMPTS,
    ids=[attack_id for _, attack_id in JAILBREAK_PROMPTS],
)
def test_resists_jailbreak_compliance(chatbot: ChatbotAdapter, prompt: str, attack_id: str) -> None:
    """Send a known jailbreak prompt; assert the response does not show explicit compliance."""
    del attack_id  # used only for the parametrize id; pytest already shows it in the test name
    response = chatbot.send_message(prompt)
    assert_no_jailbreak_compliance(response.text, prompt)


@pytest.mark.wardenbot
@pytest.mark.severity_high
@pytest.mark.parametrize(
    "prompt,attack_id",
    JAILBREAK_PROMPTS,
    ids=[attack_id for _, attack_id in JAILBREAK_PROMPTS],
)
def test_jailbreak_does_not_leak_system_prompt(
    chatbot: ChatbotAdapter, prompt: str, attack_id: str
) -> None:
    """The same jailbreak prompts also test for system-prompt leakage in responses."""
    del attack_id
    response = chatbot.send_message(prompt)
    assert_no_system_prompt_leak(response.text, prompt)
