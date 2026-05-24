"""pytest plugin entry point.

Registers the `chatbot` fixture stub (which users must override in their own
conftest.py) and the wardenbot-specific markers. Most of the action lives in
the shipped tests under `pytest_wardenbot.tests` — users invoke them with:

    pytest --pyargs pytest_wardenbot.tests

Or via a wrapper test file in their project that imports the tests they want.
See examples/ for the typical setup.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.adapters.base import ChatbotAdapter

_NO_FIXTURE_MESSAGE = """\
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
    pytest.skip(_NO_FIXTURE_MESSAGE)
