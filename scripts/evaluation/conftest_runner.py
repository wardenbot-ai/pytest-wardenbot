"""Conftest used by `run.py` to inject the current bot into the shipped tests.

This file is copied (not imported) into a temp directory per bot run so
pytest picks it up as the conftest for the --pyargs collected tests.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.business_truth import BusinessTruthFact
from scripts.evaluation.bots import chatbot_from_env


@pytest.fixture
def chatbot():
    return chatbot_from_env()


@pytest.fixture(
    params=[
        BusinessTruthFact(
            label="Standard plan price",
            question="How much does the Standard plan cost per month?",
            expected_answer="$49",
            match_type="substring",
            acceptable_variations=("49/mo", "forty-nine dollars"),
        ),
        BusinessTruthFact(
            label="Refund window",
            question="What is your refund policy?",
            expected_answer="30 days",
            match_type="substring",
        ),
        BusinessTruthFact(
            label="Support email",
            question="What's your support email address?",
            expected_answer="support@example.com",
            match_type="substring",
        ),
    ],
    ids=lambda f: f.parametrize_id(),
)
def business_truth_fact(request):
    return request.param
