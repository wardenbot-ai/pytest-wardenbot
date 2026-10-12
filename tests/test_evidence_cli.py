"""Portable commands exercise the installed package from independent directories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def cli(directory: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-m", "pytest_wardenbot.agents.evidence_cli", *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_portable_example_replays_in_subprocesses(tmp_path):
    example = Path(__file__).resolve().parents[1] / "examples/evidence/run_controls.py"
    result = subprocess.run(
        [sys.executable, str(example), "--output-dir", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "finding.html").is_file()
    regrade = json.loads((tmp_path / "regrade.json").read_text())
    assert regrade["result"]["outcome"] == "violated"
    assert regrade["execution_mode"] == "offline_regrade"
    assert regrade["evidence_authentication"] == "unverified_saved_observations"
    assert len(regrade["source_bundle_sha256"]) == 64


def test_default_redacted_bundle_can_replay_but_cannot_claim_regraded_resistance(tmp_path):
    fixture = cli(tmp_path, "fixture", "--behavior", "resistant", "--output", "finding.json")
    assert fixture.returncode == 0, fixture.stderr
    regrade = cli(tmp_path, "regrade", "finding.json")
    assert regrade.returncode == 2, regrade.stderr
    assert json.loads(regrade.stdout)["result"]["outcome"] == "inconclusive"
    replay = cli(tmp_path, "replay", "finding.json", "--output", "rerun.json")
    assert replay.returncode == 0, replay.stderr
    comparison = cli(tmp_path, "compare", "finding.json", "rerun.json", "--html", "compare.html")
    assert comparison.returncode == 0, comparison.stderr
    assert (tmp_path / "compare.html").is_file()


@pytest.mark.parametrize(
    "payload",
    [b'{"schema_version":1,"schema_version":2}', b"\xff", b"x" * (4 * 1024 * 1024 + 1)],
    ids=["duplicate-keys", "invalid-utf8", "oversized"],
)
def test_invalid_files_do_not_leak_input_in_diagnostics(tmp_path, payload):
    private = b"SYNTHETIC_PRIVATE_MARKER"
    (tmp_path / "private.json").write_bytes(payload + private)
    result = cli(tmp_path, "inspect", "private.json")
    assert result.returncode == 2
    assert "SYNTHETIC_PRIVATE_MARKER" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_missing_file_failure_is_private(tmp_path):
    result = cli(tmp_path, "inspect", "SYNTHETIC_PRIVATE_MARKER.json")
    assert result.returncode == 2
    assert "SYNTHETIC_PRIVATE_MARKER" not in result.stderr
