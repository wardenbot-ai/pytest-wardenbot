"""Pattern B, every deterministic layer, against the naive and the fixed implementation."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest

from post_summary import data, fixed, naive
from pytest_wardenbot.grading.prompt import assert_instruction_present, assert_untrusted_confined
from pytest_wardenbot.grading.structured import assert_marker_absent, assert_only_known_ids
from pytest_wardenbot.model import injection_marker, model_endpoint, mutate

BENIGN = json.loads(Path("llm_responses/post_summary/benign.json").read_text(encoding="utf-8"))
SENT_IDS = ["p1", "p2", "p3"]
NAIVE_FAILS = pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="naive: no fence, no data rule, no id binding"
)
ATTACKED = [pytest.param(naive, id="naive", marks=NAIVE_FAILS), pytest.param(fixed, id="fixed")]
BOTH = [pytest.param(naive, id="naive"), pytest.param(fixed, id="fixed")]


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer1_attack_post_stays_fenced(pipeline: ModuleType) -> None:
    case = "post_summary_layer1"
    attack = data.attack_text(injection_marker(case))
    with model_endpoint(case, script=BENIGN) as block:
        pipeline.summarize_posts(data.posts(injection_marker(case)))
    # The naive prompt JSON-encodes the posts: "json" finds the payload, outside any fence.
    assert_untrusted_confined(
        block.requests,
        payload=attack,
        fence=fixed.FENCE,
        escape=fixed.escape,
        encodings=("raw", "json"),
        forbidden=("<post", "</post"),
    )
    assert_instruction_present(block.requests, fixed.DATA_RULE)


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer2_hostile_structured_output(pipeline: ModuleType) -> None:
    case = "post_summary_layer2"
    hostile = [mutate.inject_marker(), mutate.add_item("flagged_post_ids", "p99")]
    with model_endpoint(case, script=BENIGN, mutate=hostile):
        result = pipeline.summarize_posts(data.posts(injection_marker(case)))
    assert_only_known_ids(result.flagged_post_ids, None, SENT_IDS)


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer3_exported_reply_that_followed_the_attack(pipeline: ModuleType) -> None:
    case = "post_summary_attack"
    with model_endpoint(case):
        result = pipeline.summarize_posts(data.posts(injection_marker(case)))
    assert_only_known_ids(result.flagged_post_ids, None, SENT_IDS)


@pytest.mark.parametrize("pipeline", BOTH)
def test_layer3_benign_control(pipeline: ModuleType) -> None:
    case = "post_summary_benign"
    with model_endpoint(case):
        result = pipeline.summarize_posts(data.posts(injection_marker(case)))
    assert result.themes == ["battery life", "price"]
    assert_only_known_ids(result.flagged_post_ids, None, SENT_IDS)
    assert_marker_absent(result, injection_marker(case))
