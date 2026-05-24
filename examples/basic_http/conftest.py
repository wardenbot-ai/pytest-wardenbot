"""WardenBot AI configuration for a generic HTTP chatbot."""

from __future__ import annotations

import os

import pytest

from pytest_wardenbot.adapters.http import HTTPChatbotAdapter
from pytest_wardenbot.business_truth import BusinessTruthFact


@pytest.fixture
def chatbot():
    url = os.environ.get("CHATBOT_URL", "https://your-chatbot.example.com/chat")
    token = os.environ.get("CHATBOT_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else None

    return HTTPChatbotAdapter(
        url=url,
        headers=headers,
        # TODO: change if your endpoint expects/returns different field names.
        request_field="message",
        response_field="response",
    )


@pytest.fixture(
    params=[
        BusinessTruthFact(
            label="Business hours",
            question="What are your business hours?",
            expected_answer="9 AM to 5 PM EST",  # TODO: replace
            match_type="substring",
        ),
        BusinessTruthFact(
            label="Contact email",
            question="What's your support email address?",
            expected_answer="support@example.com",  # TODO: replace
            match_type="substring",
        ),
    ],
    ids=lambda f: f.parametrize_id(),
)
def business_truth_fact(request):
    return request.param
