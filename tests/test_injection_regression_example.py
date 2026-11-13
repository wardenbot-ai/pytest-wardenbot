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


# Expected (passed, xfailed) per pattern. Attack cases are xfailed on naive and passed
# on fixed; the rest pass on both.
EXPECTED = {
    # 21 attack cases (confinement 1, fence breaks 15, hostile replies 3, replayed 2),
    # 2 benign controls and 2 hash-churn tests.
    "source_rating": (25, 21),
    # 3 attack cases, 1 benign control on both.
    "post_summary": (5, 3),
    # 3 attack cases, 1 benign control on both, 2 stream tests, 5 renderer cases.
    "doc_chat": (12, 3),
}


@pytest.mark.parametrize("pattern", list(EXPECTED))
def test_each_pattern(pattern: str) -> None:
    code, output = run_pattern(pattern)
    assert code == 0, output[-4000:]
    outcome = counts(output)
    assert outcome.get("failed", 0) == 0 and outcome.get("xpassed", 0) == 0
    passed, xfailed = EXPECTED[pattern]
    assert (outcome["passed"], outcome["xfailed"]) == (passed, xfailed)


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


def test_all_patterns_together() -> None:
    """The README's plain `pytest` in the example folder: all patterns in one process."""
    code, output = run_pattern(".")
    assert code == 0, output[-4000:]
    passed = sum(expected[0] for expected in EXPECTED.values())
    xfailed = sum(expected[1] for expected in EXPECTED.values())
    assert counts(output) == {"passed": passed, "xfailed": xfailed}
