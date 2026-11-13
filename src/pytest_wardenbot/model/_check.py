"""``python -m pytest_wardenbot.model check FOLDER``: check a response folder without a test run.

It runs the same credential scan as the loader and the recorder over every
file, validates the manifest and every ``.jsonl`` file, and reports manifest
rules whose files are missing and rules an earlier rule always preempts.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._folder import ResponseFolder
from pytest_wardenbot.model._hash import RequestHasher
from pytest_wardenbot.model._manifest import MANIFEST_NAME, Manifest, parse_manifest, shadowed_rules
from pytest_wardenbot.model._scan import scan_text

_MAX_BYTES = 20 * 1024 * 1024


def check_folder(root: Path) -> tuple[list[str], int]:
    """Problems found in a response folder, and how many files were scanned."""
    if not root.is_dir():
        return [f"{root} is not a folder."], 0
    problems: list[str] = []
    manifest: Manifest | None = None
    if (root / MANIFEST_NAME).is_file():
        try:
            manifest = parse_manifest(root / MANIFEST_NAME)
        except ModelEndpointError as error:
            problems.append(str(error))
    allow = manifest.allow_patterns if manifest is not None else ()

    scanned = 0
    folder = ResponseFolder(root, RequestHasher())
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or any(part.startswith(".") for part in relative.parts):
            continue
        if path.stat().st_size > _MAX_BYTES:
            problems.append(f"{relative}: larger than 20 MB; not scanned. Is it a reply file?")
            continue
        scanned += 1
        text = path.read_bytes().decode("utf-8", errors="replace")
        problems += [str(finding) for finding in scan_text(text, str(relative), allow)]
        if path.suffix.lower() == ".jsonl":
            try:
                folder._read_jsonl(path)
            except ModelEndpointError as error:
                if "looks like" not in str(error):  # already reported by the scan above
                    problems.append(str(error))

    if manifest is not None:
        for rule in manifest.rules:
            for target in rule.targets:
                if not (root / target).is_file():
                    problems.append(f"{rule.describe()}: {target} doesn't exist.")
        for rule, earlier in shadowed_rules(manifest):
            problems.append(
                f"{rule.describe()} can never match: {earlier.describe()} matches every "
                "request it would, and comes first."
            )
    return problems, scanned


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m pytest_wardenbot.model",
        description="Tools for pytest-wardenbot response folders.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser(
        "check",
        help="scan a response folder for credentials and check its manifest",
        description=(
            "Scan every file for credential-shaped strings (API keys, Bearer tokens, key "
            "parameters), validate the manifest and .jsonl files, and report rules whose files "
            "are missing or that an earlier rule always preempts. Exits 1 on any problem."
        ),
    )
    check.add_argument("folder", type=Path)
    arguments = parser.parse_args(argv)

    problems, scanned = check_folder(arguments.folder)
    if problems:
        print(f"{arguments.folder}: {len(problems)} problem(s)")  # noqa: T201
        for problem in problems:
            print(f"  {problem}")  # noqa: T201
        return 1
    print(f"{arguments.folder}: OK ({scanned} files checked)")  # noqa: T201
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
