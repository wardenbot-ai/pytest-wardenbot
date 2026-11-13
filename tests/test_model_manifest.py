"""Manifest rules in wardenbot-responses.toml: matching, serving and validation."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from pytest_wardenbot.model import (
    Endpoint,
    ModelEndpointError,
    ReplayMissError,
    _cases,
    injection_marker,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._hash import RequestHasher
from pytest_wardenbot.model._manifest import last_component, parse_manifest, shadowed_rules
from tests.model_support import clean_environment, post

RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    clean_environment(monkeypatch)
    monkeypatch.setattr(_cases, "_claimed", {})
    uninstall()
    root = tmp_path / "llm_responses"
    root.mkdir()
    return root


@pytest.fixture
def replay(folder: Path) -> Iterator[Endpoint]:
    endpoint = install(mode="replay", responses_dir=folder)
    try:
        yield endpoint
    finally:
        uninstall()


def manifest(folder: Path, text: str) -> None:
    (folder / "wardenbot-responses.toml").write_text('marker_seed = "rules"\n' + text)


def reply(folder: Path, name: str, text: str) -> None:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def text_of(response: Any) -> str:
    return response.json()["output_text"]


def test_first_matching_rule_wins(folder: Path, replay: Endpoint) -> None:
    reply(folder, "a.txt", "first rule")
    reply(folder, "b.txt", "second rule")
    manifest(
        folder,
        '[[response]]\ncontains = "rate"\nfile = "a.txt"\n\n'
        '[[response]]\ncontains = "rate"\nfile = "b.txt"\n',
    )
    with model_endpoint("order"):
        assert text_of(post(replay, RESPONSES, {"input": "please rate"})) == "first rule"


@pytest.mark.parametrize(
    ("rule_case", "block_case"),
    [
        ("tests/test_x.py::test_attack", "tests/test_x.py::test_attack"),
        ("test_attack", "tests/test_x.py::test_attack"),
        ("test_attack[1.5]", "tests/test_x.py::Suite::test_attack[1.5]"),
        ("test_rating", "app.tests.Pipeline.test_rating"),
        ("source_rating_attack", "source_rating_attack"),
    ],
)
def test_case_matches_the_full_id_or_last_component(
    folder: Path, replay: Endpoint, rule_case: str, block_case: str
) -> None:
    reply(folder, "attack.txt", "matched")
    manifest(folder, f'[[response]]\ncase = "{rule_case}"\nfile = "attack.txt"\n')
    with model_endpoint(block_case):
        assert text_of(post(replay, RESPONSES, {"input": "x"})) == "matched"


def test_last_component() -> None:
    assert last_component("tests/a.py::Suite::test_x[1.5-b]") == "test_x[1.5-b]"
    assert last_component("app.tests.Suite.test_x") == "test_x"
    assert last_component("plain") == "plain"
    # Explicit case names are not unittest ids: they stay whole.
    assert last_component("summarizer.v2") == "summarizer.v2"
    assert last_component("gpt-4.1-attack") == "gpt-4.1-attack"
    assert last_component("test_x[1.5]") == "test_x[1.5]"


def test_each_match_field(folder: Path, replay: Endpoint) -> None:
    body = {"model": "gpt-x", "input": [{"role": "user", "content": "Rate source 3"}]}
    digest = RequestHasher().digest("POST", RESPONSES, body)
    for name in ("path", "model", "regex", "hash"):
        reply(folder, f"{name}.txt", name)
    manifest(
        folder,
        '[[response]]\npath = "/v1/chat/completions"\nfile = "path.txt"\n\n'
        '[[response]]\nmodel = "gpt-y"\nfile = "model.txt"\n\n'
        '[[response]]\nregex = "Rate source \\\\d+$"\nmodel = "gpt-x"\nfile = "regex.txt"\n\n'
        f'[[response]]\nrequest_hash = "{digest}"\nfile = "hash.txt"\n',
    )
    with model_endpoint("fields"):
        assert text_of(post(replay, RESPONSES, body)) == "regex"
        chat = post(replay, CHAT, {"messages": []}).json()
        assert chat["choices"][0]["message"]["content"] == "path"
        assert text_of(post(replay, RESPONSES, {**body, "model": "gpt-y"})) == "model"
    manifest(folder, f'[[response]]\nrequest_hash = "{digest}"\nfile = "hash.txt"\n')
    with model_endpoint("fields"):
        assert text_of(post(replay, RESPONSES, body)) == "hash"


@pytest.mark.parametrize(("then", "third"), [("repeat_last", "batch 2"), ("fail", None)])
def test_files_sequences(folder: Path, replay: Endpoint, then: str, third: str | None) -> None:
    reply(folder, "batch_1.txt", "batch 1")
    reply(folder, "batch_2.txt", "batch 2")
    manifest(
        folder,
        '[[response]]\ncontains = "Rate"\n'
        f'files = ["batch_1.txt", "batch_2.txt"]\nthen = "{then}"\n',
    )
    for case in ("naive", "fixed"):  # each block starts at the first file
        expectation = pytest.raises(ModelEndpointError) if third is None else nullcontext()
        with expectation, model_endpoint(case):
            texts = [post(replay, RESPONSES, {"input": f"Rate {n}"}) for n in range(3)]
            assert [text_of(t) for t in texts[:2]] == ["batch 1", "batch 2"]
            if third is not None:
                assert text_of(texts[2]) == third
            else:
                assert texts[2].status_code == 500


def test_files_exhaustion_message(folder: Path, replay: Endpoint) -> None:
    reply(folder, "only.txt", "only")
    manifest(folder, '[[response]]\ncontains = "x"\nfiles = ["only.txt"]\n')
    with (
        pytest.raises(ModelEndpointError, match=r"served all 1 of its files, and this was call 2"),
        model_endpoint("exhausted"),
    ):
        post(replay, RESPONSES, {"input": "x"})
        post(replay, RESPONSES, {"input": "x"})


def test_jsonl_rules_pick_an_entry_whatever_the_hash(folder: Path, replay: Endpoint) -> None:
    lines = [
        {"request": {"input": "logged request A"}, "response": "entry one", "case": "posts_a"},
        {"request": {"input": "logged request B"}, "response": "entry two", "id": "evt-2"},
        {"request": {"input": "logged request C"}, "response": "entry three", "case": "posts_b"},
    ]
    reply(folder, "exports/posts.jsonl", "\n".join(json.dumps(line) for line in lines))
    manifest(
        folder,
        '[[response]]\ncase = "posts_attack"\nfile = "exports/posts.jsonl"\n'
        'where = { case = "posts_b" }\n\n'
        '[[response]]\ncase = "by_line"\nfile = "exports/posts.jsonl"\nline = 1\n\n'
        '[[response]]\ncase = "by_field"\nfile = "exports/posts.jsonl"\nwhere = { id = "evt-2" }\n',
    )
    for case, expected in [
        ("posts_attack", "entry three"),
        ("by_line", "entry one"),
        ("by_field", "entry two"),
    ]:
        with model_endpoint(case):
            # A different request than the logged one: the rule picks the entry anyway.
            assert text_of(post(replay, RESPONSES, {"input": "today's request"})) == expected


def test_jsonl_rule_with_no_matching_entry(folder: Path, replay: Endpoint) -> None:
    reply(folder, "log.jsonl", json.dumps({"request": {"input": "x"}, "response": "r"}))
    manifest(folder, '[[response]]\ncase = "c"\nfile = "log.jsonl"\nline = 5\n')
    with pytest.raises(ModelEndpointError, match="has no entry with line 5"), model_endpoint("c"):
        post(replay, RESPONSES, {"input": "x"})


def test_rule_files_get_placeholders(folder: Path, replay: Endpoint) -> None:
    reply(folder, "hostile.json", '{"reason": "obeyed {{wardenbot.marker}}"}')
    manifest(folder, '[[response]]\ncase = "hostile"\nfile = "hostile.json"\nrecord = false\n')
    with model_endpoint("hostile"):
        structured = json.loads(text_of(post(replay, RESPONSES, {"input": "x"})))
        assert structured == {"reason": f"obeyed {injection_marker()}"}


def test_missing_rule_file(folder: Path, replay: Endpoint) -> None:
    manifest(folder, '[[response]]\ncase = "gone"\nfile = "nowhere.txt"\n')
    with (
        pytest.raises(ModelEndpointError, match=r"names nowhere\.txt, which doesn't exist"),
        model_endpoint("gone"),
    ):
        post(replay, RESPONSES, {"input": "x"})


def test_the_miss_report_explains_each_rule(folder: Path, replay: Endpoint) -> None:
    manifest(
        folder,
        '[[response]]\ncase = "other_case"\nfile = "a.txt"\n\n'
        '[[response]]\ncontains = "absent text"\nfile = "b.txt"\n\n'
        '[[response]]\nmodel = "gpt-y"\nfile = "c.txt"\n',
    )
    with pytest.raises(ReplayMissError) as error, model_endpoint("tests/t.py::test_case"):
        post(replay, RESPONSES, {"model": "gpt-x", "input": "x"})
    report = str(error.value)
    assert "rule 1 (case = 'other_case'): case: 'other_case' is not" in report
    assert "rule 2 (contains = 'absent text'): contains: 'absent text' is not in" in report
    assert "rule 3 (model = 'gpt-y'): model: 'gpt-y' is not 'gpt-x'" in report


def test_case_rules_never_match_outside_blocks(folder: Path, replay: Endpoint) -> None:
    reply(folder, "a.txt", "x")
    manifest(folder, '[[response]]\ncase = "c"\nfile = "a.txt"\n')
    assert post(replay, RESPONSES, {"input": "x"}).status_code == 500
    assert "outside any model_endpoint block" in str(replay.errors[-1])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('[[response]]\ncase = "x"\nfiel = "a.txt"\n', r"unknown key\(s\) 'fiel'"),
        ('[[response]]\ncase = "x"\n', "exactly one of `file` or `files`"),
        ('[[response]]\nfile = "a"\nfiles = ["b"]\n', "exactly one of `file` or `files`"),
        ('[[response]]\nfile = "a.txt"\nline = 1\n', "only apply to a .jsonl `file`"),
        ('[[response]]\nfile = "a.jsonl"\n', "needs exactly one of `line` or `where`"),
        ('[[response]]\nfile = "a.jsonl"\nline = 1\nwhere = {case = "x"}\n', "exactly one of"),
        ('[[response]]\nfile = "a.jsonl"\nline = 0\n', "whole number from 1"),
        ('[[response]]\nfile = "a.jsonl"\nwhere = {}\n', "non-empty table"),
        ('[[response]]\nregex = "("\nfile = "a.txt"\n', "not a valid regular expression"),
        ('[[response]]\nfile = "a.txt"\nthen = "fail"\n', "only applies to `files`"),
        ('[[response]]\nfiles = ["a"]\nthen = "loop"\n', "must be one of fail, repeat_last"),
        ('[[response]]\nfiles = ["a.jsonl"]\n', "can't name a .jsonl file"),
        ('[[response]]\nfile = "../outside.txt"\n', "inside the response folder"),
        ('[[response]]\nfile = "/etc/passwd"\n', "inside the response folder"),
        ('[[response]]\nfile = "C:secrets.json"\n', "inside the response folder"),
        ('[[response]]\nfile = "a.txt"\nrecord = "no"\n', "true or false"),
        ('[[response]]\ncase = ""\nfile = "a.txt"\n', "non-empty string"),
        ("rules = []\n", r"unknown key\(s\) 'rules'"),
        ("allow_patterns = ['(']\n", "allow_patterns"),
        ("response = 3\n", "must be \\[\\[response\\]\\] tables"),
    ],
)
def test_validation_names_the_file_and_rule(folder: Path, text: str, message: str) -> None:
    manifest(folder, text)
    with pytest.raises(ModelEndpointError, match=message) as error:
        parse_manifest(folder / "wardenbot-responses.toml")
    assert "wardenbot-responses.toml" in str(error.value)


def test_shadowed_rules(folder: Path) -> None:
    manifest(
        folder,
        '[[response]]\ncase = "x"\nfile = "a.txt"\n\n'
        '[[response]]\ncase = "x"\ncontains = "y"\nfile = "b.txt"\n\n'
        '[[response]]\ncontains = "a"\nfile = "c.txt"\n\n'
        '[[response]]\ncontains = "b"\nfile = "d.txt"\n',
    )
    found = shadowed_rules(parse_manifest(folder / "wardenbot-responses.toml"))
    assert [(rule.index, earlier.index) for rule, earlier in found] == [(2, 1)]
    manifest(folder, '[[response]]\nfile = "all.txt"\n\n[[response]]\ncase = "x"\nfile = "a"\n')
    found = shadowed_rules(parse_manifest(folder / "wardenbot-responses.toml"))
    assert [(rule.index, earlier.index) for rule, earlier in found] == [(2, 1)]
    assert "matches everything" in found[0][1].describe()


def test_jsonl_rules_with_an_upper_case_extension_and_inferred_fields(
    folder: Path, replay: Endpoint
) -> None:
    lines = [
        {"request": {"input": "a"}, "response": "inferred path", "case": 7},
        {"request": {"messages": []}, "response": "chat entry"},
    ]
    reply(folder, "Exports/LOG.JSONL", "\n".join(json.dumps(line) for line in lines))
    manifest(
        folder,
        '[[response]]\ncase = "by_path"\nfile = "Exports/LOG.JSONL"\n'
        'where = { path = "/v1/chat/completions" }\n\n'
        '[[response]]\ncase = "by_number"\nfile = "Exports/LOG.JSONL"\nwhere = { case = 7 }\n',
    )
    with model_endpoint("by_path"):
        assert text_of(post(replay, RESPONSES, {"input": "x"})) == "chat entry"
    with model_endpoint("by_number"):
        assert text_of(post(replay, RESPONSES, {"input": "x"})) == "inferred path"


def test_rule_targets_must_stay_inside_the_folder(
    folder: Path, replay: Endpoint, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (folder / "link.txt").symlink_to(outside)
    manifest(folder, '[[response]]\ncase = "escape"\nfile = "link.txt"\n')
    with (
        pytest.raises(ModelEndpointError, match="outside the response folder"),
        model_endpoint("escape"),
    ):
        post(replay, RESPONSES, {"input": "x"})


def test_a_rewritten_manifest_is_reread_even_with_the_same_mtime(folder: Path) -> None:
    import os

    from pytest_wardenbot.model._manifest import load_manifest

    manifest(folder, '[[response]]\ncase = "a"\nfile = "a.txt"\n')
    path = folder / "wardenbot-responses.toml"
    first = load_manifest(folder)
    stat = path.stat()
    manifest(
        folder,
        '[[response]]\ncase = "a"\nfile = "a.txt"\n\n[[response]]\ncase = "b"\nfile = "b.txt"\n',
    )
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = load_manifest(folder)
    assert first is not None and second is not None
    assert len(first.rules) == 1 and len(second.rules) == 2
