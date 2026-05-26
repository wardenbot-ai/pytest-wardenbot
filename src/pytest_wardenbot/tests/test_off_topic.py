"""Off-topic deflection tests.

**Audience:** scoped chatbots — customer-service, sales, support, or any
chatbot intentionally narrowed to a domain. These tests assert the bot
deflects unrelated requests rather than engaging at length.

**General-purpose bots will fail these tests by design.** That's intended:
if your bot is supposed to answer "explain quantum entanglement in 500
words," then the off-topic tests are not for you. Options to handle that:

1. Override `wardenbot_off_topic_prompts` to return `()` (empty tuple) —
   the parametrized test will then collect zero cases and pass trivially.
2. Override with your own bot-appropriate corpus (questions that ARE
   off-topic for your specific bot, even if not for a general assistant).
3. Skip the test entirely with `pytest --deselect ...`.

The shipped corpus targets customer-service-style scope (e.g. "summarize
quantum physics" against a billing bot). Override the
`wardenbot_off_topic_prompts` fixture in your conftest.py to substitute.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.grading.deterministic import assert_response_refuses


@pytest.mark.wardenbot
@pytest.mark.severity_medium
def test_deflects_off_topic_requests(chatbot: ChatbotAdapter, prompt: str, attack_id: str) -> None:
    """Send an off-topic prompt; assert the chatbot refuses to engage.

    Scoped chatbots (customer-service, support) pass this; general-purpose
    bots fail by design — see this module's docstring.
    """
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_response_refuses(response.text, prompt, context="off-topic deflection")
