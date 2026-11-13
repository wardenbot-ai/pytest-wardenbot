"""The model endpoint under Django's own test runner, and under pytest-django.

The example project in tests/fixtures/django_project calls install() at the
top of its test settings. Each run is a separate process, as in a real project.
"""

from __future__ import annotations

import multiprocessing
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from pytest_wardenbot.model._config import _CI_MARKERS

pytest.importorskip("django")
pytest.importorskip("openai")

PROJECT = Path(__file__).resolve().parent / "fixtures" / "django_project"
CI_VARIABLES = ("CI", *_CI_MARKERS)
PASSED = re.compile(r"^OK(?: \(.*\))?$", re.MULTILINE)
FAILED = re.compile(r"^FAILED \(", re.MULTILINE)


def environment(**extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "WARDENBOT_", "PYTEST_", "DJANGO_"))
        and key not in CI_VARIABLES
        and key not in {"PIPELINE_MAIN_PID", "EXPECT_PARALLEL", "TEST_START_METHOD"}
    }
    if sys.platform == "darwin":
        env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"  # for the fork case
    return {**env, **extra}


def manage(*args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "manage.py", "test", *args],
        cwd=PROJECT,
        env=environment(**extra),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_manage_py_test_runs_pipeline_tests() -> None:
    result = manage("--tag", "injection", "-v", "2")
    assert result.returncode == 0, result.stderr[-3000:]
    assert "Ran 4 tests" in result.stderr
    assert PASSED.search(result.stderr), result.stderr[-3000:]


@pytest.mark.parametrize("mode", ["replay", "scripted"])
def test_the_mode_comes_from_the_configuration_or_the_environment(mode: str) -> None:
    extra = {"WARDENBOT_MODEL_MODE": mode} if mode == "scripted" else {}
    result = manage(
        "pipeline.tests.ScriptedPipeline",
        "pipeline.tests.ModeCheck",
        EXPECTED_WARDENBOT_MODE=mode,
        **extra,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    assert PASSED.search(result.stderr)


def test_ci_refuses_record_under_the_unittest_runner() -> None:
    result = manage(WARDENBOT_MODEL_MODE="record", OPENAI_API_KEY="unused", CI="true")
    assert result.returncode != 0
    assert "mode 'record' calls the real model API" in result.stderr
    assert "refuses to run in CI" in result.stderr


@pytest.mark.parametrize(
    "method",
    [
        pytest.param("spawn"),
        pytest.param(
            "forkserver",
            marks=pytest.mark.skipif(
                "forkserver" not in multiprocessing.get_all_start_methods(), reason="POSIX only"
            ),
        ),
    ],
)
def test_parallel_workers_get_their_own_endpoints(method: str) -> None:
    result = manage("--parallel", "2", TEST_START_METHOD=method, EXPECT_PARALLEL="1")
    assert result.returncode == 0, result.stderr[-3000:]
    assert "Ran 5 tests" in result.stderr  # ModeCheck skips itself


def assert_fails_cleanly_under_fork(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0
    assert "forked from the one that installed the wardenbot model endpoint" in result.stderr
    # A reported test failure, not a crashed runner (Django needs tblib to send it back).
    assert FAILED.search(result.stderr), result.stderr[-3000:]
    assert "cannot pickle" not in result.stderr


@pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"}, reason="fork-based Django workers: POSIX only"
)
def test_fork_based_parallel_runs_fail_cleanly() -> None:
    pytest.importorskip("tblib")
    assert_fails_cleanly_under_fork(manage("--parallel", "2", TEST_START_METHOD="fork"))


def test_parallel_runs_with_the_default_start_method() -> None:
    """No start method forced: fork (Linux before 3.14) fails cleanly, others work."""
    result = manage("--parallel", "2", EXPECT_PARALLEL="1")
    if multiprocessing.get_start_method() == "fork":
        pytest.importorskip("tblib")
        assert_fails_cleanly_under_fork(result)
    else:
        assert result.returncode == 0, result.stderr[-3000:]
        assert "Ran 5 tests" in result.stderr  # ModeCheck skips itself


def test_pytest_django_installs_the_endpoint_before_ready() -> None:
    pytest.importorskip("pytest_django")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "pytest_django",
            "--ds=project.settings",  # no install() in these settings: the plugin does it
            "pytest_checks",  # the project's pyproject.toml turns the cache off
            "-q",
        ],
        cwd=PROJECT,
        env=environment(),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-2000:]
    assert "1 passed" in result.stdout
