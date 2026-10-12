"""Verify portable evidence using only the installed core package, offline."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from pytest_wardenbot.agents._privacy import PrivacyPolicy
from pytest_wardenbot.agents.evidence import (
    evidence_to_dict,
    evidence_to_json,
    execute_fixture,
    make_replay_manifest,
)
from pytest_wardenbot.agents.evidence_reports import evidence_to_junit, render_evidence_html


def check(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    bundle = asyncio.run(
        execute_fixture(
            make_replay_manifest("vulnerable"), privacy=PrivacyPolicy(include_content=True)
        )
    )
    original = directory / "finding.json"
    original.write_text(
        evidence_to_json(bundle, policy=PrivacyPolicy(include_content=True)), encoding="utf-8"
    )
    (directory / "finding.html").write_text(render_evidence_html(bundle), encoding="utf-8")
    (directory / "finding.xml").write_text(evidence_to_junit(bundle), encoding="utf-8")
    for command in ("inspect", "regrade", "replay"):
        output = directory / f"{command}.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest_wardenbot.agents.evidence_cli",
                command,
                str(original),
                "--output",
                str(output),
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        expected_exit = 1 if command == "regrade" else 0
        if result.returncode != expected_exit:
            raise RuntimeError("Portable evidence control failed")
        payload = json.loads(output.read_text(encoding="utf-8"))
        if command == "regrade":
            if payload["result"]["outcome"] != "violated":
                raise RuntimeError("Saved observed effect was not preserved")
            if payload["execution_mode"] != "offline_regrade":
                raise RuntimeError("Saved re-grading lost its execution mode")
        if command == "inspect" and payload != evidence_to_dict(bundle):
            raise RuntimeError("Bundle changed during validation")
    # The vulnerability is deliberate: CLI regrade exits one, JUnit has a failure.
    # The replay command exits zero when the expected vulnerable fixture reproduces.
    sys.stdout.write("Portable fixture replay and offline re-grading verified.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, help="Retain the synthetic example artifacts.")
    args = parser.parse_args()
    if args.output_dir:
        check(args.output_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="wardenbot-evidence-") as temporary:
            check(Path(temporary))


if __name__ == "__main__":
    main()
