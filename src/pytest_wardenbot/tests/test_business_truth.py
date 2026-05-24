"""Business-truth verification tests.

Parametrized over a user-supplied list of `BusinessTruthFact` entries. Asks the
chatbot each fact's question and verifies the response matches the expected
answer per the configured `match_type`.

Users provide the list by overriding the `business_truth_fact` fixture in their
own conftest.py — see `pytest_wardenbot.plugin._NO_TRUTH_FACTS_MESSAGE` for the
template skipped users see.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.business_truth import BusinessTruthFact, assert_truth_fact_match


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_business_truth(chatbot: ChatbotAdapter, business_truth_fact: BusinessTruthFact) -> None:
    """Send the fact's question to the chatbot; assert the answer matches."""
    response = chatbot.send_message(business_truth_fact.question)
    assert_truth_fact_match(response.text, business_truth_fact)
