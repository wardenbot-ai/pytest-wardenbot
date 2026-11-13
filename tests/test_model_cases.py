"""Case names for model requests, under pytest and plain unittest."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model._cases import case_dirname, current_case


def test_explicit_case_wins() -> None:
    assert current_case("source_rating_attack") == "source_rating_attack"


def test_explicit_case_cannot_be_blank() -> None:
    with pytest.raises(WardenBotConfigError, match="cannot be empty"):
        current_case("  ")


def test_pytest_node_id_without_phase(request: pytest.FixtureRequest) -> None:
    assert current_case() == request.node.nodeid


def test_outside_a_test_asks_for_a_case(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    with pytest.raises(WardenBotConfigError, match=r"model_endpoint\(case="):
        current_case()


def test_unittest_id_from_the_running_test_case(tmp_path: Path) -> None:
    module = tmp_path / "test_plain.py"
    module.write_text(
        textwrap.dedent(
            """
            import unittest
            from pytest_wardenbot.model._cases import current_case

            def helper():
                return current_case()

            class Pipeline(unittest.TestCase):
                def test_rating(self):
                    print("CASE=" + helper())
            """
        ),
        encoding="utf-8",
    )
    env = {**os.environ, "PYTEST_CURRENT_TEST": "tests/outer.py::test_parent (call)"}
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "-v", "test_plain"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    # The inherited PYTEST_CURRENT_TEST is ignored: pytest isn't running there.
    assert "CASE=test_plain.Pipeline.test_rating" in result.stdout


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("tests/test_x.py::test_attack", "tests_test_x.py__test_attack"),
        ("tests/test_x.py::test_a[naive-1.5]", "tests_test_x.py__test_a_naive-1.5_"),
        ("app.tests.Pipeline.test_rating", "app.tests.Pipeline.test_rating"),
        ("source_rating_attack", "source_rating_attack"),
        ("..", "__"),
        (".", "_"),
        ("...", "___"),
        ("../../etc", ".._.._etc"),
        ("", "_"),
    ],
)
def test_case_dirname(case: str, expected: str) -> None:
    assert case_dirname(case) == expected


def test_case_dirname_never_escapes_the_folder() -> None:
    for case in ("..", "../..", "/etc/passwd", "a/../../b", "..\\..\\x"):
        name = case_dirname(case)
        assert "/" not in name and "\\" not in name
        assert name not in {".", ".."}


def test_long_case_names_keep_a_prefix_and_hash() -> None:
    long_a = "tests/test_pipeline.py::test_rating[" + "a" * 300 + "]"
    long_b = "tests/test_pipeline.py::test_rating[" + "a" * 299 + "b]"
    name_a, name_b = case_dirname(long_a), case_dirname(long_b)
    assert len(name_a) <= 120 and len(name_b) <= 120
    assert name_a.startswith("tests_test_pipeline.py__test_rating_aaa")
    assert name_a != name_b
    assert case_dirname(long_a) == name_a


def test_pytest_id_ignored_when_pytest_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "_pytest.runner")
    with pytest.raises(WardenBotConfigError, match="Cannot tell which test is running"):
        current_case()


def test_unittest_case_in_process(monkeypatch: pytest.MonkeyPatch) -> None:
    import unittest

    seen: list[str] = []

    class Pipeline(unittest.TestCase):
        def test_rating(self) -> None:
            seen.append(current_case())

    monkeypatch.delitem(sys.modules, "_pytest.runner")
    result = unittest.TextTestRunner(stream=io.StringIO()).run(Pipeline("test_rating"))
    assert result.wasSuccessful()
    assert seen == [Pipeline("test_rating").id()]
