"""The reference examples in examples/injection_regression run as a consumer project would.

Each pattern's tests run in a separate pytest process from the example's own
directory, with its pyproject.toml and response folder, and no API key. Attack
cases are strict xfails on the naive implementation, so a naive version that
stops failing fails the run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("openai")

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "injection_regression"


def clean_env() -> dict[str, str]:
    """The environment without keys, endpoint settings or pytest's own variables."""
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "WARDENBOT_", "PYTEST_"))
    }


def run_pattern(pattern: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", pattern, "-q", "-p", "no:cacheprovider"],
        cwd=EXAMPLE,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result.returncode, result.stdout + "\n" + result.stderr


def counts(output: str) -> dict[str, int]:
    summary = next(
        line for line in reversed(output.splitlines()) if re.search(r"\d+ (passed|failed)", line)
    )
    return {kind: int(number) for number, kind in re.findall(r"(\d+) (\w+)", summary)}


def test_pattern_a_source_rating() -> None:
    code, output = run_pattern("source_rating")
    assert code == 0, output[-4000:]
    outcome = counts(output)
    assert outcome.get("failed", 0) == 0 and outcome.get("xpassed", 0) == 0
    # 21 attack cases (confinement 1, fence breaks 15, hostile replies 3, replayed 2)
    # are red on naive and green on fixed; plus 2 benign controls and 2 hash-churn tests.
    assert outcome["xfailed"] == 21 and outcome["passed"] == 25


def test_pattern_b_post_summary() -> None:
    code, output = run_pattern("post_summary")
    assert code == 0, output[-4000:]
    outcome = counts(output)
    assert outcome.get("failed", 0) == 0 and outcome.get("xpassed", 0) == 0
    assert outcome["xfailed"] == 3 and outcome["passed"] == 5


def test_pattern_b_exports_are_up_to_date() -> None:
    result = subprocess.run(
        [sys.executable, "make_exports.py", "--check"],
        cwd=EXAMPLE,
        env=clean_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
