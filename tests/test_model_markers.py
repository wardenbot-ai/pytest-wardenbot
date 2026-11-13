"""Injection markers and canaries: stable per case in seeded modes, random otherwise."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot.canary import canary_present
from pytest_wardenbot.model import (
    MARKER_PREFIX,
    ModelEndpointError,
    _markers,
    case_canary,
    injection_marker,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._markers import read_seed, write_seed
from tests.model_support import clean_environment

MARKER = re.compile(r"^WBMARK-[a-z2-7]{16}$")
CANARY = re.compile(r"^WBCANARY-[A-Za-z0-9_-]{32}$")


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    clean_environment(monkeypatch)
    monkeypatch.delenv("WARDENBOT_CANARY", raising=False)
    monkeypatch.setattr(_markers, "_random", {})
    monkeypatch.setattr(_markers, "_seed_cache", {})
    monkeypatch.setattr(_markers, "_warned_default_seed", False)
    uninstall()
    yield
    uninstall()


def seeded_folder(tmp_path: Path, seed: str = "test-seed") -> Path:
    folder = tmp_path / "llm_responses"
    folder.mkdir()
    (folder / "wardenbot-responses.toml").write_text(f'marker_seed = "{seed}"\n')
    return folder


def expected_marker(seed: str, case: str) -> str:
    digest = hmac.new(seed.encode(), f"marker\0{case}".encode(), hashlib.sha256).digest()
    return MARKER_PREFIX + base64.b32encode(digest).decode().lower()[:16]


def test_seeded_markers_are_derived_from_the_seed_and_case(tmp_path: Path) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    marker = injection_marker("source_rating_attack")
    assert MARKER.match(marker)
    assert marker == expected_marker("test-seed", "source_rating_attack")
    assert injection_marker("source_rating_attack") == marker
    assert injection_marker("source_rating_benign") != marker
    canary = case_canary("source_rating_attack")
    assert CANARY.match(canary)
    assert canary != marker


def test_the_same_marker_in_another_process(tmp_path: Path) -> None:
    folder = seeded_folder(tmp_path)
    install(mode="replay", responses_dir=folder)
    code = (
        "from pytest_wardenbot.model import install, injection_marker, case_canary; "
        f"install(mode='replay', responses_dir={str(folder)!r}); "
        "print(injection_marker('shared'), case_canary('shared'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert result.stdout.split() == [injection_marker("shared"), case_canary("shared")]


def test_a_different_seed_gives_different_markers(tmp_path: Path) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path, "one"))
    first = injection_marker("case")
    uninstall()
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "wardenbot-responses.toml").write_text('marker_seed = "two"\n')
    install(mode="replay", responses_dir=tmp_path / "other")
    assert injection_marker("case") != first


def test_markers_follow_the_active_block_then_the_test_id(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    with model_endpoint("explicit_case", script="x"):
        assert injection_marker() == injection_marker("explicit_case")
    assert injection_marker() == expected_marker("test-seed", request.node.nodeid)


@pytest.mark.parametrize("mode", ["scripted", "live", None])
def test_random_markers_are_stable_within_a_process(mode: str | None) -> None:
    if mode is not None:
        install(mode=mode)
    first = injection_marker("case")
    assert MARKER.match(first)
    assert injection_marker("case") == first
    assert injection_marker("other") != first
    assert case_canary("case") == case_canary("case")
    code = "from pytest_wardenbot.model import injection_marker; print(injection_marker('case'))"
    other_process = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert other_process.stdout.strip() != first


def test_canary_present_finds_markers_the_model_mangled(tmp_path: Path) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    marker = injection_marker("case")
    split = marker[:6] + "​" + marker[6:]
    assert canary_present(f"Rating: relevant. {marker.upper()}", marker)
    assert canary_present(f"... {split} ...", marker)
    assert canary_present(f"**{marker[:9]}** {marker[9:]}", marker)


def test_replay_without_a_seed_warns_once_and_uses_the_default(tmp_path: Path) -> None:
    folder = tmp_path / "no_seed"
    folder.mkdir()
    install(mode="replay", responses_dir=folder)
    with pytest.warns(UserWarning, match="No marker_seed"):
        marker = injection_marker("case")
    assert marker == expected_marker("wardenbot", "case")
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        injection_marker("another case")  # warned once already


def test_configured_canary_is_used_as_is(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WARDENBOT_CANARY", "WBCANARY-fixed-for-deployment")
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    assert case_canary("anything") == "WBCANARY-fixed-for-deployment"


def test_write_seed_keeps_the_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "folder"
    folder.mkdir()
    rules = (
        "# hand-written rules\n"
        "[[response]]\n"
        'case = "source_rating_attack"\n'
        'file = "source_rating/attack_batch.json"\n'
        "record = false\n"
    )
    manifest = folder / "wardenbot-responses.toml"
    manifest.write_text(rules, encoding="utf-8")
    seed = write_seed(folder)
    text = manifest.read_text(encoding="utf-8")
    assert text.endswith(rules)
    parsed = tomllib.loads(text)
    assert parsed["marker_seed"] == seed
    assert parsed["response"][0]["record"] is False
    assert write_seed(folder) == seed  # idempotent
    assert manifest.read_text(encoding="utf-8") == text


def test_write_seed_creates_the_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "new" / "folder"
    seed = write_seed(folder)
    assert read_seed(folder) == seed and len(seed) >= 20


def test_invalid_seeds_are_reported(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "wardenbot-responses.toml").write_text("marker_seed = 3\n")
    with pytest.raises(ModelEndpointError, match="marker_seed must be a non-empty string"):
        read_seed(folder)
    (folder / "wardenbot-responses.toml").write_text("marker_seed = [\n")
    with pytest.raises(ModelEndpointError, match="Cannot read"):
        read_seed(folder)
    assert read_seed(None) is None
    assert read_seed(tmp_path / "missing") is None


def test_a_block_canary_is_used_as_is(tmp_path: Path) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    with model_endpoint("case", script="x", canary="WBCANARY-from-the-fixture"):
        assert case_canary() == "WBCANARY-from-the-fixture"
        assert case_canary("case") == "WBCANARY-from-the-fixture"
        assert case_canary("another") != "WBCANARY-from-the-fixture"
    assert case_canary("case") != "WBCANARY-from-the-fixture"


def test_the_fixture_canary_beats_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WARDENBOT_CANARY", "WBCANARY-from-the-environment")
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    with model_endpoint("case", script="x", canary="WBCANARY-from-the-fixture"):
        assert case_canary() == "WBCANARY-from-the-fixture"
    assert case_canary("case") == "WBCANARY-from-the-environment"


def test_canary_must_be_a_string(tmp_path: Path) -> None:
    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    with pytest.raises(TypeError, match="canary must be a string"):
        model_endpoint("case", script="x", canary=b"bytes")  # type: ignore[arg-type]


def _write_seed_in_a_process(folder: str, queue: Any) -> None:
    queue.put(write_seed(Path(folder)))


def test_concurrent_record_processes_agree_on_one_seed(tmp_path: Path) -> None:
    import multiprocessing

    folder = tmp_path / "shared"
    folder.mkdir()
    (folder / "wardenbot-responses.toml").write_text('[[response]]\ncase = "a"\nfile = "a.txt"\n')
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_write_seed_in_a_process, args=(str(folder), queue))
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    seeds = {queue.get(timeout=60) for _ in processes}
    for process in processes:
        process.join(timeout=60)
    text = (folder / "wardenbot-responses.toml").read_text()
    assert len(seeds) == 1 and text.count("marker_seed") == 1
    assert tomllib.loads(text)["marker_seed"] == seeds.pop()
    assert not (folder / ".wardenbot-seed.lock").exists()


def test_a_written_seed_is_seen_at_once(tmp_path: Path) -> None:
    folder = tmp_path / "fresh"
    folder.mkdir()
    (folder / "wardenbot-responses.toml").write_text("")
    assert read_seed(folder) is None  # cached as "no seed"
    seed = write_seed(folder)
    assert read_seed(folder) == seed


def _marker_in_a_forked_child(queue: Any) -> None:
    queue.put(injection_marker("forked case"))


@pytest.mark.skipif(
    "fork" not in __import__("multiprocessing").get_all_start_methods(), reason="needs fork"
)
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a_forked_child_keeps_seeded_markers(tmp_path: Path) -> None:
    import multiprocessing

    install(mode="replay", responses_dir=seeded_folder(tmp_path))
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_marker_in_a_forked_child, args=(queue,))
    process.start()
    child = queue.get(timeout=30)
    process.join(timeout=30)
    assert child == injection_marker("forked case")
