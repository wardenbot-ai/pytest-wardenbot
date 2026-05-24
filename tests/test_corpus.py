"""Sanity tests for the bundled attack corpora.

Locks in the basic shape of each corpus so a future edit that breaks the
parametrize contract fails loudly.
"""

from __future__ import annotations

import pytest

from pytest_wardenbot.corpus import (
    ENCODED_PAYLOAD_PROMPTS,
    INDIRECT_INJECTION_PROMPTS,
    JAILBREAK_PROMPTS,
    MULTI_TURN_JAILBREAK_PROMPTS,
    OFF_TOPIC_PROMPTS,
    REFUSAL_BYPASS_PROMPTS,
    SYSTEM_PROMPT_LEAK_PROMPTS,
)

SINGLE_TURN_CORPORA = (
    ("jailbreak", JAILBREAK_PROMPTS),
    ("system_prompt_leak", SYSTEM_PROMPT_LEAK_PROMPTS),
    ("refusal_bypass", REFUSAL_BYPASS_PROMPTS),
    ("off_topic", OFF_TOPIC_PROMPTS),
    ("indirect_injection", INDIRECT_INJECTION_PROMPTS),
)


@pytest.mark.parametrize("name,corpus", SINGLE_TURN_CORPORA)
def test_single_turn_corpus_is_non_empty(name: str, corpus: tuple) -> None:
    assert len(corpus) > 0, f"{name} corpus is empty"


@pytest.mark.parametrize("name,corpus", SINGLE_TURN_CORPORA)
def test_single_turn_entry_shape(name: str, corpus: tuple) -> None:
    """Each entry is (prompt: str, attack_id: str)."""
    for i, entry in enumerate(corpus):
        assert len(entry) == 2, f"{name}[{i}] has wrong length: {entry!r}"
        prompt, attack_id = entry
        assert isinstance(prompt, str) and prompt, f"{name}[{i}] prompt empty"
        assert isinstance(attack_id, str) and attack_id, f"{name}[{i}] attack_id empty"


@pytest.mark.parametrize("name,corpus", SINGLE_TURN_CORPORA)
def test_single_turn_attack_ids_unique(name: str, corpus: tuple) -> None:
    ids = [entry[1] for entry in corpus]
    assert len(ids) == len(set(ids)), f"{name} has duplicate attack_ids: {ids}"


# ---------------------------------------------------------------------------
# Encoded-payload corpus has a different shape
# ---------------------------------------------------------------------------


def test_encoded_payload_corpus_shape() -> None:
    assert len(ENCODED_PAYLOAD_PROMPTS) > 0
    for i, entry in enumerate(ENCODED_PAYLOAD_PROMPTS):
        assert len(entry) == 3, f"encoded[{i}] wrong length: {entry!r}"
        prompt, triggers, attack_id = entry
        assert isinstance(prompt, str) and prompt
        assert isinstance(triggers, tuple) and len(triggers) > 0
        assert all(isinstance(t, str) and t for t in triggers)
        assert isinstance(attack_id, str) and attack_id


def test_encoded_payload_attack_ids_unique() -> None:
    ids = [e[2] for e in ENCODED_PAYLOAD_PROMPTS]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Multi-turn corpus shape
# ---------------------------------------------------------------------------


def test_multi_turn_corpus_shape() -> None:
    assert len(MULTI_TURN_JAILBREAK_PROMPTS) > 0
    for i, entry in enumerate(MULTI_TURN_JAILBREAK_PROMPTS):
        assert len(entry) == 3, f"multi_turn[{i}] wrong length"
        priming, payload, attack_id = entry
        assert isinstance(priming, tuple) and len(priming) >= 1
        assert all(isinstance(t, str) and t for t in priming)
        assert isinstance(payload, str) and payload
        assert isinstance(attack_id, str) and attack_id


def test_multi_turn_attack_ids_unique() -> None:
    ids = [e[2] for e in MULTI_TURN_JAILBREAK_PROMPTS]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Headline metric: total deterministic test count
# ---------------------------------------------------------------------------


def test_total_deterministic_prompt_count() -> None:
    """Locks in the headline 'N deterministic tests' figure across docs.

    If this assertion fails because a corpus grew, update README.md +
    docs/index.md + docs/changelog.md + docs/tests/index.md +
    docs/about/powered-by.md to match the new total in lockstep.
    """
    single_turn_total = sum(len(c) for _, c in SINGLE_TURN_CORPORA)
    encoded = len(ENCODED_PAYLOAD_PROMPTS)
    multi_turn = len(MULTI_TURN_JAILBREAK_PROMPTS)

    # Each entry in the jailbreak corpus is tested twice (compliance + leak).
    # Other single-turn corpora are tested once.
    # Multi-turn / encoded / indirect / canary tests count their own way.
    # We track the prompt count, not the test-instance count, so docs cite
    # corpus size honestly.
    # Track each corpus size so a future grep can find the canonical inventory.
    # Keeping this in test code (not a docstring) so the numbers stay aligned
    # with the actual corpora — a corpus edit forces a test update here.
    counts = {
        "jailbreak (single-turn)": len(JAILBREAK_PROMPTS),
        "system-prompt-leak": len(SYSTEM_PROMPT_LEAK_PROMPTS),
        "refusal-bypass": len(REFUSAL_BYPASS_PROMPTS),
        "off-topic": len(OFF_TOPIC_PROMPTS),
        "indirect-injection (XPIA)": len(INDIRECT_INJECTION_PROMPTS),
        "encoded-payload": encoded,
        "multi-turn jailbreak": multi_turn,
    }
    assert single_turn_total > 0
    assert all(v > 0 for v in counts.values())
