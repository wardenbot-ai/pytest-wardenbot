"""Indirect prompt-injection (XPIA) tests.

For each entry in the indirect-injection corpus, send a prompt whose body
contains a smuggled directive (e.g., a 'system note' embedded in a
document the bot is asked to summarize) and assert the chatbot's response
does not show signs of compliance with the embedded directive.

Especially relevant for chatbots that ingest user-controlled content during
their work — RAG-based assistants, document summarizers, email triagers,
translation tools. v0.2 will broaden coverage via RAMPART integration; v0.1
ships a starter set.

Corpus comes from the `wardenbot_indirect_injection_prompts` fixture, which
defaults to the bundled `INDIRECT_INJECTION_PROMPTS`. Override in your
conftest.py to substitute or extend.
"""

from __future__ import annotations

from typing import Any

import pytest

from pytest_wardenbot._corpus_override import resolve_corpus
from pytest_wardenbot.adapters.base import ChatbotAdapter
from pytest_wardenbot.corpus.indirect_injection import INDIRECT_INJECTION_PROMPTS
from pytest_wardenbot.grading.deterministic import (
    assert_no_jailbreak_compliance,
    assert_no_system_prompt_leak,
)


def pytest_generate_tests(metafunc: Any) -> None:
    if {"prompt", "attack_id"} <= set(metafunc.fixturenames):
        corpus = resolve_corpus(
            metafunc,
            "wardenbot_indirect_injection_prompts",
            INDIRECT_INJECTION_PROMPTS,
        )
        metafunc.parametrize(
            ("prompt", "attack_id"),
            corpus,
            ids=[entry[1] for entry in corpus],
        )


@pytest.mark.wardenbot
@pytest.mark.severity_high
def test_resists_indirect_injection(chatbot: ChatbotAdapter, prompt: str, attack_id: str) -> None:
    """Send a prompt with a smuggled directive in the body; assert no compliance."""
    del attack_id
    response = chatbot.send_message(prompt)
    # An indirect-injection success looks identical to a direct-injection
    # success in the response: compliance markers + (sometimes) system prompt
    # leak markers. We assert against both.
    assert_no_jailbreak_compliance(response.text, prompt)
    assert_no_system_prompt_leak(response.text, prompt)
