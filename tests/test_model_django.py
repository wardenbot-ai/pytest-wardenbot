"""The model endpoint under Django's own test runner, and under pytest-django.

The example project in tests/fixtures/django_project calls install() at the
top of its test settings. Each run is a separate process, as in a real project.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("django")
pytest.importorskip("openai")

PROJECT = Path(__file__).resolve().parent / "fixtures" / "django_project"
CI_VARIABLES = ("CI", "GITHUB_ACTIONS", "JENKINS_URL", "TF_BUILD", "TEAMCITY_VERSION", "BUILDKITE")


def environment(**extra: str) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "WARDENBOT_", "PYTEST_", "DJANGO_"))
        and key not in CI_VARIABLES
    }
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
    assert "OK" in result.stderr


def test_scripted_mode_from_the_environment() -> None:
    result = manage("pipeline.tests.ScriptedPipeline", WARDENBOT_MODEL_MODE="scripted")
    assert result.returncode == 0, result.stderr[-3000:]


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
    result = manage("--parallel", "2", TEST_START_METHOD=method)
    assert result.returncode == 0, result.stderr[-3000:]
    assert "Ran 4 tests" in result.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="fork-based Django workers: Linux only")
def test_fork_based_parallel_runs_fail_loudly() -> None:
    result = manage("--parallel", "2", TEST_START_METHOD="fork")
    assert result.returncode != 0
    assert "forked from the one that installed the wardenbot model endpoint" in result.stderr


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
            "-p",
            "no:cacheprovider",
            "pytest_checks",
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
