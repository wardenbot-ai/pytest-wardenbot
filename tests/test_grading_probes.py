"""Accuracy of the deterministic chatbot graders on a labeled response set.

`tests/fixtures/grading_probes.json` holds real chatbot responses to the
shipped refusal-bypass, off-topic and system-prompt-leak prompts (five model
families, six system prompts) plus hand-written edge cases. Each response is
labeled with the verdict the shipped test should give. Labels were assigned by
reading the responses, before the graders were run on them.

The contract checked here:

- With a canary and the known system prompt configured, every unambiguous
  probe gets the labeled verdict, except the listed known limitations.
- With nothing configured (phrasing checks only), no well-behaved response
  fails. Leaks without framing are expected to pass in that mode.
- Every known limitation is still misgraded, so the published list stays
  accurate. If a change fixes one, remove it from the list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS
from pytest_wardenbot.grading.deterministic import (
    assert_maintains_refusal_under_bypass,
    assert_no_system_prompt_leak,
    assert_response_refuses,
)

_DATA: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "grading_probes.json").read_text(encoding="utf-8")
)
_PROMPTS = {
    attack_id: prompt
    for prompt, attack_id in (
        *OFF_TOPIC_PROMPTS,
        *REFUSAL_BYPASS_PROMPTS,
        *SYSTEM_PROMPT_LEAK_PROMPTS,
    )
}
_PROBES: list[dict[str, Any]] = _DATA["probes"]


def _verdict(probe: dict[str, Any], *, configured: bool) -> str:
    """Grade `probe` the way the shipped test does; return 'pass' or 'fail'."""
    text = probe["text"]
    prompt = _PROMPTS[probe["prompt_id"]]
    system_prompt = (
        _DATA["system_prompts"][probe["system_prompt"]]
        if configured and probe["system_prompt"]
        else None
    )
    canary = probe["canary"] if configured else None
    try:
        if probe["test"] == "refusal_bypass":
            assert_no_system_prompt_leak(text, prompt, system_prompt=system_prompt, canary=canary)
            assert_maintains_refusal_under_bypass(text, prompt)
        elif probe["test"] == "off_topic":
            assert_response_refuses(text, prompt)
        else:
            assert_no_system_prompt_leak(text, prompt, system_prompt=system_prompt, canary=canary)
    except AssertionError:
        return "fail"
    return "pass"


def _ids(probes: list[dict[str, Any]]) -> list[str]:
    return [f"{p['split']}:{p['id']}" for p in probes]


_GRADED = [p for p in _PROBES if p["label"] != "ambiguous" and not p["known_limitation"]]
_WELL_BEHAVED = [p for p in _PROBES if p["label"] == "pass"]
_LIMITATIONS = [p for p in _PROBES if p["known_limitation"]]


def test_probe_file_is_well_formed() -> None:
    ids = [(p["split"], p["id"]) for p in _PROBES]
    assert len(ids) == len(set(ids))
    for probe in _PROBES:
        assert probe["test"] in {"refusal_bypass", "off_topic", "system_prompt_leak"}
        assert probe["label"] in {"pass", "fail", "ambiguous"}
        assert probe["prompt_id"] in _PROMPTS
        assert probe["system_prompt"] is None or probe["system_prompt"] in _DATA["system_prompts"]
        if probe["known_limitation"]:
            assert probe["label"] == "fail"


@pytest.mark.parametrize("probe", _GRADED, ids=_ids(_GRADED))
def test_configured_grading_matches_label(probe: dict[str, Any]) -> None:
    assert _verdict(probe, configured=True) == probe["label"], probe["note"] or probe["text"][:200]


@pytest.mark.parametrize("probe", _WELL_BEHAVED, ids=_ids(_WELL_BEHAVED))
def test_phrasing_only_grading_never_fails_a_well_behaved_response(probe: dict[str, Any]) -> None:
    assert _verdict(probe, configured=False) == "pass", probe["note"] or probe["text"][:200]


@pytest.mark.parametrize("probe", _LIMITATIONS, ids=_ids(_LIMITATIONS))
def test_known_limitations_are_still_misgraded(probe: dict[str, Any]) -> None:
    assert _verdict(probe, configured=True) == "pass", (
        "This known limitation is now graded correctly. Remove it from the known "
        "limitations in grading_probes.json and docs/reference/grading-accuracy.md."
    )
