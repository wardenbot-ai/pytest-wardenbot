"""Off-topic deflection tests.

For a scoped chatbot (support / sales / customer-service), asserts that the
bot deflects unrelated requests rather than engaging at length. A general-
purpose assistant will fail these tests — that's intended; skip the file or
override `OFF_TOPIC_PROMPTS` if your chatbot really is general-purpose.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.grading.deterministic import assert_response_refuses


@pytest.mark.wardenbot
@pytest.mark.severity_medium
@pytest.mark.parametrize(
    "prompt,attack_id",
    OFF_TOPIC_PROMPTS,
    ids=[attack_id for _, attack_id in OFF_TOPIC_PROMPTS],
)
def test_deflects_off_topic_requests(chatbot: ChatbotAdapter, prompt: str, attack_id: str) -> None:
    """Send an off-topic prompt; assert the chatbot refuses to engage."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_response_refuses(response.text, prompt, context="off-topic deflection")
