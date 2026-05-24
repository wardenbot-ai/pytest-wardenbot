"""Multi-turn jailbreak tests.

For each entry in the multi-turn corpus, send the priming turns first to
establish conversational context, then send the payload prompt and assert
the response does not show explicit signs of jailbreak compliance or
system-prompt leakage.

Requires a session-aware chatbot adapter (HTTPChatbotAdapter with
`session_id`, OpenAIChatAdapter, AnthropicMessagesAdapter, or any adapter
that honors the `session_id` parameter on `send_message`). Stateless
adapters will run the test but each turn looks fresh to the underlying bot
— the priming never lands and the test will over-report success.

Corpus comes from the `wardenbot_multi_turn_jailbreak_prompts` fixture,
which defaults to the bundled `MULTI_TURN_JAILBREAK_PROMPTS`. Override in
your conftest.py to substitute or extend.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from pytest_wardenbot._corpus_override import resolve_corpus
from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.multi_turn import MULTI_TURN_JAILBREAK_PROMPTS
from pytest_wardenbot.grading.deterministic import (
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
)


def pytest_generate_tests(metafunc: Any) -> None:
    if {"priming_turns", "payload_prompt", "attack_id"} <= set(metafunc.fixturenames):
        corpus = resolve_corpus(
            metafunc,
            "wardenbot_multi_turn_jailbreak_prompts",
            MULTI_TURN_JAILBREAK_PROMPTS,
        )
        metafunc.parametrize(
            ("priming_turns", "payload_prompt", "attack_id"),
            corpus,
            ids=[entry[2] for entry in corpus],
        )


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_resists_multi_turn_jailbreak(
    chatbot: ChatbotAdapter,
    priming_turns: tuple[str, ...],
    payload_prompt: str,
    attack_id: str,
) -> None:
    """Send priming turns then the payload; assert no jailbreak compliance."""
    session_id = f"wardenbot-multiturn-{attack_id}-{uuid.uuid4().hex[:8]}"
    try:
        for turn in priming_turns:
            chatbot.send_message(turn, session_id=session_id)

        response = chatbot.send_message(payload_prompt, session_id=session_id)
        assert_no_jailbreak_compliance(response.text, payload_prompt)
        assert_no_system_prompt_leak(response.text, payload_prompt)
    finally:
        chatbot.reset_session(session_id)
