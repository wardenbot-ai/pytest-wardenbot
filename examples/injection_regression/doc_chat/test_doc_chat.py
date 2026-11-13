"""Pattern C, every deterministic layer, against the naive and the fixed implementation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import ModuleType
from urllib.parse import urlsplit

import httpx
import pytest

from doc_chat import fixed, naive
from pytest_wardenbot.grading.prompt import assert_instruction_present, assert_untrusted_confined
from pytest_wardenbot.grading.structured import assert_links_allowed
from pytest_wardenbot.model import Script, model_endpoint, mutate

DOCUMENTS = json.loads(Path("doc_chat/documents.json").read_text(encoding="utf-8"))
ATTACK_DOCUMENT = DOCUMENTS[2]["text"]
ALLOWED_HOSTS = sorted({urlsplit(doc["url"]).hostname for doc in DOCUMENTS})
QUESTION = "How should I charge my laptop?"
BENIGN_ANSWER = "Charge the laptop between 20% and 80% to extend battery life."
CANARY_HOST = "canary.wardenbot.invalid"
NAIVE_FAILS = pytest.mark.xfail(strict=True, reason="naive: documents in instructions, renders all")
ATTACKED = [pytest.param(naive, id="naive", marks=NAIVE_FAILS), pytest.param(fixed, id="fixed")]
BOTH = [pytest.param(naive, id="naive"), pytest.param(fixed, id="fixed")]


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer1_documents_stay_fenced_in_the_user_turn(pipeline: ModuleType) -> None:
    with model_endpoint("doc_chat_layer1", script=BENIGN_ANSWER) as block:
        pipeline.answer(QUESTION, DOCUMENTS)
    assert_untrusted_confined(
        block.requests, payload=ATTACK_DOCUMENT, fence=fixed.FENCE, escape=fixed.escape
    )
    assert_instruction_present(block.requests, fixed.DATA_RULE)


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer2_hostile_links_and_images_are_not_rendered(pipeline: ModuleType) -> None:
    hostile = [mutate.add_links(CANARY_HOST), mutate.add_images(CANARY_HOST)]
    with model_endpoint("doc_chat_layer2", script=BENIGN_ANSWER, mutate=hostile):
        rendered = pipeline.answer(QUESTION, DOCUMENTS)
    assert_links_allowed(rendered, ALLOWED_HOSTS)


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer3_streamed_reply_that_followed_the_attack(pipeline: ModuleType) -> None:
    with model_endpoint("doc_chat_attack"):
        rendered = pipeline.answer(QUESTION, DOCUMENTS)
    assert_links_allowed(rendered, ALLOWED_HOSTS)


@pytest.mark.parametrize("pipeline", BOTH)
def test_layer3_benign_control(pipeline: ModuleType) -> None:
    with model_endpoint("doc_chat_benign"):
        rendered = pipeline.answer(QUESTION, DOCUMENTS)
    assert 'href="https://docs.example.com/battery-guide"' in rendered  # on-site links stay
    assert_links_allowed(rendered, ALLOWED_HOSTS)


def test_the_hand_written_stream_replays_byte_for_byte() -> None:
    recorded = Path("llm_responses/cases/doc_chat_attack/1.sse").read_bytes()
    with model_endpoint("doc_chat_attack"):
        reply = httpx.post(
            os.environ["OPENAI_BASE_URL"] + "/responses",
            json={"model": "gpt-4.1-mini", "input": QUESTION, "stream": True},
            timeout=10,
        )
    assert reply.content == recorded


def test_a_scripted_stream_parses_too() -> None:
    with model_endpoint("doc_chat_scripted", script=Script.text(BENIGN_ANSWER)):
        assert fixed.answer(QUESTION, DOCUMENTS) == f"<p>{BENIGN_ANSWER}</p>"
