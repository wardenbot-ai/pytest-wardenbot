"""pytest plugin entry point.

Registers fixtures that users override in their own `conftest.py`:

- `chatbot` — required. The chatbot under test.
- `business_truth_fact` — optional. Parametrized list of `BusinessTruthFact`
  entries for the shipped `test_business_truth` test.

Also registers wardenbot-specific markers (`wardenbot`, `severity_high|medium|low`)
so `--strict-markers` doesn't reject them.

Most shipped tests live under `pytest_wardenbot.tests`; invoke with:

    pytest --pyargs pytest_wardenbot.tests
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.business_truth import BusinessTruthFact

_NO_CHATBOT_FIXTURE_MESSAGE = """\
No `chatbot` fixture configured.

pytest-wardenbot ships tests that need a chatbot to probe. You connect your
chatbot by adding a fixture to your conftest.py. Minimal example:

    import os
    import pytest
    from pytest_wardenbot.adapters.http import HTTPChatbotAdapter

    @pytest.fixture
    def chatbot():
        return HTTPChatbotAdapter(
            url="https://your-chatbot.example.com/chat",
            headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
            request_field="message",
            response_field="reply",
        )

See https://github.com/pardamike/pytest-wardenbot#quickstart for more.
"""

_NO_TRUTH_FACTS_MESSAGE = """\
No `business_truth_fact` fixture configured.

The shipped `test_business_truth` test is parametrized over a user-supplied list
of business facts your chatbot should always answer correctly. Add a
parametrized fixture to your conftest.py:

    import pytest
    from pytest_wardenbot.business_truth import BusinessTruthFact

    @pytest.fixture(params=[
        BusinessTruthFact(
            label="Standard plan price",
            question="How much does the Standard plan cost per month?",
            expected_answer="$49",
            match_type="substring",
            acceptable_variations=("49/mo", "forty-nine dollars"),
        ),
        BusinessTruthFact(
            label="Business hours",
            question="What are your business hours?",
            expected_answer="9 AM to 5 PM EST",
            match_type="substring",
        ),
    ], ids=lambda f: f.parametrize_id())
    def business_truth_fact(request):
        return request.param

Skip this test entirely if your chatbot is not customer-facing.
"""


def pytest_configure(config: pytest.Config) -> None:
    """Register wardenbot-specific markers so --strict-markers doesn't reject them."""
    config.addinivalue_line("markers", "wardenbot: marks tests provided by pytest-wardenbot")
    config.addinivalue_line("markers", "severity_high: high-severity wardenbot test")
    config.addinivalue_line("markers", "severity_medium: medium-severity wardenbot test")
    config.addinivalue_line("markers", "severity_low: low-severity wardenbot test")


@pytest.fixture
def chatbot() -> ChatbotAdapter:
    """The chatbot under test.

    Users MUST override this in their own conftest.py to point at their chatbot.
    If left at the default, all wardenbot tests skip with a helpful message.
    """
    pytest.skip(_NO_CHATBOT_FIXTURE_MESSAGE)


@pytest.fixture
def business_truth_fact() -> BusinessTruthFact:
    """A single business-truth fact to verify.

    Users override this in their own conftest.py with a parametrized fixture
    listing their business's facts. If left at the default, the shipped
    `test_business_truth` test skips with a helpful message.
    """
    pytest.skip(_NO_TRUTH_FACTS_MESSAGE)
