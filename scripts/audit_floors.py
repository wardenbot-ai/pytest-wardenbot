"""Fail if a declared dependency floor has a known vulnerability.

Reads every ``>=`` lower bound in ``pyproject.toml`` (core dependencies and
user-facing extras) and audits exactly those versions with pip-audit. A floor
is the oldest version we tell resolvers is fine, so it should not be one with
a published advisory. Run it with pip-audit installed:

    python scripts/audit_floors.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Contributor-only extras are pinned or audited elsewhere.
SKIP_EXTRAS = {"dev", "docs"}
# Advisories accepted for a floor, with the reason and when it goes away.
ACCEPTED = {
    # CVE-2025-71176: pytest's /tmp/pytest-of-{user} handling lets other local
    # users on a shared UNIX machine interfere with test runs. Fixed in pytest
    # 9.0.3, which drops the pytest 8 line; the floor moves to 9.0.3 in 0.7.0,
    # announced in the 0.6.1 changelog. Resolvers already pick a fixed pytest
    # unless a project pins an older one.
    "PYSEC-2026-1845": "pytest floor moves to 9.0.3 in 0.7.0",
    "GHSA-6w46-j5rx-g56g": "pytest floor moves to 9.0.3 in 0.7.0",
}
_FLOOR = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*>=\s*([^,;\s]+)")


def floors() -> set[tuple[str, str]]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    for extra, values in project["optional-dependencies"].items():
        if extra not in SKIP_EXTRAS:
            requirements += values
    found: set[tuple[str, str]] = set()
    for requirement in requirements:
        match = _FLOOR.match(requirement)
        if match:
            found.add((re.sub(r"[-_.]+", "-", match[1]).lower(), match[3]))
    return found


def main() -> int:
    pins = sorted(floors())
    listed = ", ".join(f"{name}=={version}" for name, version in pins)
    print(f"Auditing dependency floors: {listed}", flush=True)  # noqa: T201
    # pip-audit rejects two versions of one package in a file, so a package
    # with different floors in different extras is audited in a second file.
    batches: list[dict[str, str]] = []
    for name, version in pins:
        batch = next((batch for batch in batches if name not in batch), None)
        if batch is None:
            batches.append(batch := {})
        batch[name] = version
    status = 0
    with tempfile.TemporaryDirectory() as directory:
        for index, batch in enumerate(batches):
            path = Path(directory) / f"floors-{index}.txt"
            path.write_text("".join(f"{name}=={version}\n" for name, version in batch.items()))
            command = [sys.executable, "-m", "pip_audit", "--no-deps", "--disable-pip"]
            command += ["--progress-spinner", "off", "--desc", "-r", str(path)]
            for advisory in ACCEPTED:
                command += ["--ignore-vuln", advisory]
            status = max(status, subprocess.run(command, check=False).returncode)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
