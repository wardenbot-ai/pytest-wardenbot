"""Multi-turn jailbreak tests.

For each entry in the multi-turn corpus, send the priming turns first to
establish conversational context, then send the payload prompt and assert
the response does not show explicit signs of jailbreak compliance or
system-prompt leakage.

Requires a session-aware chatbot adapter (OpenAIChatAdapter,
AnthropicMessagesAdapter, OpenAIAssistantsAdapter, or an HTTPChatbotAdapter
pointed at a session-aware endpoint). Stateless adapters will run the test but
each turn looks fresh to the underlying bot — the priming never lands and the
test over-reports success. To catch that, the test emits a `UserWarning` when
the adapter has not declared `stateful = True`; set that attribute on your
adapter (e.g. `HTTPChatbotAdapter(..., stateful=True)`) once your endpoint
maintains session state, to confirm the test is meaningful and silence the
warning.

Corpus comes from the `wardenbot_multi_turn_jailbreak_prompts` fixture,
which defaults to the bundled `MULTI_TURN_JAILBREAK_PROMPTS`. Override in
your conftest.py to substitute or extend.
"""

from __future__ import annotations

import uuid
import warnings

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading.deterministic import (
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
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
    if not getattr(chatbot, "stateful", False):
        warnings.warn(
            "test_resists_multi_turn_jailbreak ran against an adapter that has not "
            "declared itself session-aware (no `stateful = True`). Multi-turn priming "
            "only lands if your adapter maintains conversation context across "
            "send_message calls for a given session_id; otherwise every turn looks "
            "fresh to the bot and this test passes trivially (false confidence). If "
            "your endpoint IS session-aware, set `stateful = True` on your adapter "
            "(e.g. HTTPChatbotAdapter(..., stateful=True)) to silence this.",
            UserWarning,
            stacklevel=2,
        )
    session_id = f"wardenbot-multiturn-{attack_id}-{uuid.uuid4().hex[:8]}"
    try:
        for turn in priming_turns:
            chatbot.send_message(turn, session_id=session_id)

        response = chatbot.send_message(payload_prompt, session_id=session_id)
        assert_no_jailbreak_compliance(response.text, payload_prompt)
        assert_no_system_prompt_leak(response.text, payload_prompt)
    finally:
        chatbot.reset_session(session_id)
