"""Check a CycloneDX SBOM before it is attested and published.

GitHub's attestation action only accepts CycloneDX JSON with a bomFormat,
specVersion and serialNumber, so the release would fail at that step without
them. Also checks the SBOM describes this release's core install.

    python scripts/check_sbom.py sbom.cdx.json
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = {"pytest", "pydantic", "httpx"}


def check(path: Path) -> list[str]:
    sbom = json.loads(path.read_text(encoding="utf-8"))
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    problems = []
    if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("specVersion"):
        problems.append("not CycloneDX JSON with a specVersion")
    if not re.fullmatch(r"urn:uuid:[0-9a-f-]{36}", str(sbom.get("serialNumber", ""))):
        problems.append("missing serialNumber (GitHub's attestation action requires it)")
    component = sbom.get("metadata", {}).get("component", {})
    if component.get("name") != "pytest-wardenbot" or component.get("version") != version:
        problems.append(
            f"describes {component.get('name')} {component.get('version')}, not {version}"
        )
    names = {str(item.get("name", "")).lower() for item in sbom.get("components", [])}
    if not names >= CORE:
        problems.append(f"missing core dependencies: {sorted(CORE - names)}")
    if "pip" in names:
        problems.append("lists pip, so it was generated from the wrong environment")
    return problems


def main() -> int:
    problems = check(Path(sys.argv[1]))
    for problem in problems:
        print(f"SBOM problem: {problem}", file=sys.stderr)  # noqa: T201
    if not problems:
        print(f"SBOM OK: {sys.argv[1]}")  # noqa: T201
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
