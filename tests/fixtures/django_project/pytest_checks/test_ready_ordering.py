"""Under pytest-django: the endpoint is installed before django.setup() runs ready()."""

import os

from pipeline import llm

from pytest_wardenbot.model import model_endpoint


def test_ready_client_was_built_against_the_endpoint() -> None:
    assert os.environ["OPENAI_BASE_URL"] == llm.READY_BASE_URL
    assert llm.READY_BASE_URL.startswith("http://127.0.0.1:")
    with model_endpoint(script="Ready."):
        assert llm.summarize("x", llm.READY_CLIENT) == "Ready."
