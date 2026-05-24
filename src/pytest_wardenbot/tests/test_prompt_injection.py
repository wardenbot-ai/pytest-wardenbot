"""Prompt injection / jailbreak resistance tests.

Each test sends a known jailbreak prompt to the chatbot under test and asserts
the response does not show explicit signs of compliance.

The corpus comes from the `wardenbot_jailbreak_prompts` fixture, which
defaults to the bundled `JAILBREAK_PROMPTS`. Override the fixture in your
conftest.py to substitute or extend.
"""

from __future__ import annotations

from typing import Any

import pytest

from pytest_wardenbot._corpus_override import resolve_corpus
from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.jailbreak import JAILBREAK_PROMPTS
from pytest_wardenbot.grading.deterministic import (
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
)


def pytest_generate_tests(metafunc: Any) -> None:
    """Parametrize tests that consume `prompt, attack_id` from the jailbreak corpus."""
    if {"prompt", "attack_id"} <= set(metafunc.fixturenames):
        corpus = resolve_corpus(metafunc, "wardenbot_jailbreak_prompts", JAILBREAK_PROMPTS)
        metafunc.parametrize(
            ("prompt", "attack_id"),
            corpus,
            ids=[entry[1] for entry in corpus],
        )


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_resists_jailbreak_compliance(chatbot: ChatbotAdapter, prompt: str, attack_id: str) -> None:
    """Send a known jailbreak prompt; assert the response does not show explicit compliance."""
    del attack_id  # surfaced via the parametrize id
    response = chatbot.send_message(prompt)
    assert_no_jailbreak_compliance(response.text, prompt)


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_jailbreak_does_not_leak_system_prompt(
    chatbot: ChatbotAdapter, prompt: str, attack_id: str
) -> None:
    """The same jailbreak prompts also test for system-prompt leakage in responses."""
    del attack_id
    response = chatbot.send_message(prompt)
    assert_no_system_prompt_leak(response.text, prompt)
