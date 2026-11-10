"""Refusal-bypass tests.

Sends prompts that use adversarial framings (roleplay, educational pretext,
hypothetical scenarios) intended to make the chatbot rationalize compliance
with a request it would otherwise refuse. The assertion: the chatbot
maintains its refusal stance (refusal phrasing present, compliance phrasing
absent) and, because the bundled prompts target the system prompt, does not
leak it (canary, verbatim overlap or disclosure phrasing).

Corpus comes from the `wardenbot_refusal_bypass_prompts` fixture, which
defaults to the bundled `REFUSAL_BYPASS_PROMPTS`. Override in your
conftest.py to substitute or extend.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading.deterministic import (
    assert_maintains_refusal_under_bypass,
    assert_no_system_prompt_leak,
)


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_maintains_refusal_under_bypass(
    chatbot: ChatbotAdapter,
    prompt: str,
    attack_id: str,
    wardenbot_refusal_markers: tuple[str, ...],
    wardenbot_compliance_markers: tuple[str, ...],
    wardenbot_canary: str | None,
    wardenbot_system_prompt: str | None,
) -> None:
    """Send a bypass-framed prompt; assert the chatbot refuses cleanly."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_no_system_prompt_leak(
        response.text, prompt, system_prompt=wardenbot_system_prompt, canary=wardenbot_canary
    )
    assert_maintains_refusal_under_bypass(
        response.text,
        prompt,
        extra_refusal_markers=wardenbot_refusal_markers,
        extra_compliance_markers=wardenbot_compliance_markers,
    )
