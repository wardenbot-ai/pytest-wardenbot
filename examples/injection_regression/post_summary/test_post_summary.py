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

REPLIES = Path(__file__).parent.parent / "llm_responses" / "post_summary"
BENIGN = json.loads((REPLIES / "benign.json").read_text(encoding="utf-8"))
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
    """A model that flags a marked id and an invented one.

    themes and summary are free text the application shows as model output;
    the field it acts on, flagged_post_ids, must hold only ids it sent, and so
    never the attacker's marker.
    """
    case = "post_summary_layer2"
    hostile = [
        mutate.add_item("flagged_post_ids", "p2"),
        mutate.inject_marker(["flagged_post_ids[0]"]),  # "p2 WBMARK-..."
        mutate.add_item("flagged_post_ids", "p99"),
    ]
    with model_endpoint(case, script=BENIGN, mutate=hostile):
        result = pipeline.summarize_posts(data.posts(injection_marker(case)))
    assert_marker_absent(result.flagged_post_ids, injection_marker(case))
    assert_only_known_ids(result.flagged_post_ids, None, SENT_IDS)


@pytest.mark.parametrize("pipeline", ATTACKED)
def test_layer3_exported_reply_that_followed_the_attack_cant_invent_ids(
    pipeline: ModuleType,
) -> None:
    """The exported reply obeyed the attack: no themes, nothing to report, a made-up flag.

    No pipeline can tell a suppressed summary from a real one, so fixed still
    returns the empty themes. What it guarantees is that the made-up id p9 is
    never acted on.
    """
    case = "post_summary_attack"
    with model_endpoint(case):
        result = pipeline.summarize_posts(data.posts(injection_marker(case)))
    assert_only_known_ids(result.flagged_post_ids, None, SENT_IDS)


@pytest.mark.parametrize("pipeline", BOTH)
def test_layer3_benign_control(pipeline: ModuleType) -> None:
    case = "post_summary_benign"
    with model_endpoint(case):
        result = pipeline.summarize_posts(data.benign_posts())  # no attack post at all
    assert result.themes == ["battery life", "price"]
    assert_only_known_ids(result.flagged_post_ids, None, ["p1", "p2"])
    assert_marker_absent(result, injection_marker(case))
