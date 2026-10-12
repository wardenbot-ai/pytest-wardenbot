"""Local evidence commands. No provider calls or code loading from bundle data."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pytest_wardenbot.agents._privacy import PrivacyPolicy
from pytest_wardenbot.agents.contracts import Outcome
from pytest_wardenbot.agents.evidence import (
    EvidenceBundle,
    compare_evidence,
    comparison_to_dict,
    evidence_to_json,
    execute_fixture,
    load_evidence_bundle,
    make_replay_manifest,
    regrade_evidence,
    replay_evidence,
)
from pytest_wardenbot.agents.evidence_reports import evidence_to_junit, render_evidence_html
from pytest_wardenbot.agents.reporting import result_to_dict

_MAX_BYTES = 4 * 1024 * 1024


def _load(path: Path) -> EvidenceBundle:
    if not path.is_file():
        raise ValueError("Input must be a regular evidence file")
    with path.open("rb") as stream:
        raw = stream.read(_MAX_BYTES + 1)
    if len(raw) > _MAX_BYTES:
        raise ValueError("Evidence file exceeds the input bound")
    return load_evidence_bundle(raw.decode("utf-8"))


def _write(text: str, destination: Path | None) -> None:
    if destination is None:
        sys.stdout.write(text + "\n")
    else:
        destination.write_text(text + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, description in (
        ("inspect", "Validate and display saved evidence; no execution."),
        ("regrade", "Grade saved observations; no target execution."),
        ("replay", "Execute the bound built-in synthetic fixture; no provider requests."),
    ):
        command = commands.add_parser(name, help=description)
        command.add_argument("bundle", type=Path)
        command.add_argument("--output", type=Path, help="Write JSON here instead of stdout.")
        if name != "regrade":
            command.add_argument("--html", type=Path, help="Also write a standalone HTML view.")
            command.add_argument("--junit", type=Path, help="Also write strict JUnit evidence.")
    fixture = commands.add_parser("fixture", help="Run the fixed public synthetic control.")
    fixture.add_argument(
        "--behavior", choices=("vulnerable", "resistant", "no_exposure"), default="vulnerable"
    )
    fixture.add_argument("--output", type=Path)
    fixture.add_argument("--html", type=Path)
    fixture.add_argument("--junit", type=Path)
    fixture.add_argument(
        "--include-synthetic-content",
        action="store_true",
        help="Include this built-in fixture's public content for exact offline re-grading.",
    )
    compare = commands.add_parser("compare", help="Compare saved outcomes and fingerprints.")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("current", type=Path)
    compare.add_argument("--output", type=Path)
    compare.add_argument("--html", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "fixture":
            bundle = asyncio.run(
                execute_fixture(
                    make_replay_manifest(args.behavior),
                    privacy=PrivacyPolicy(include_content=args.include_synthetic_content),
                )
            )
        elif args.command == "compare":
            baseline, current = _load(args.baseline), _load(args.current)
            comparison = compare_evidence(baseline, current)
            _write(json.dumps(comparison_to_dict(comparison), indent=2), args.output)
            if args.html:
                _write(render_evidence_html(current, comparison=comparison), args.html)
            return 0  # Comparison is descriptive; it is not a security gate.
        else:
            bundle = _load(args.bundle)
            if args.command == "regrade":
                result = regrade_evidence(bundle)
                _write(
                    json.dumps(
                        {
                            "schema_version": "1",
                            "execution_mode": "offline_regrade",
                            "source_bundle_sha256": bundle.bundle_fingerprint,
                            "evidence_authentication": "unverified_saved_observations",
                            "result": result_to_dict(result),
                        },
                        indent=2,
                        allow_nan=False,
                    ),
                    args.output,
                )
                if result.outcome is Outcome.RESISTED:
                    return 0
                return 1 if result.outcome is Outcome.VIOLATED else 2
            if args.command == "replay":
                bundle = asyncio.run(replay_evidence(bundle))
        export_policy = PrivacyPolicy(
            include_content=(args.command == "fixture" and args.include_synthetic_content)
        )
        _write(evidence_to_json(bundle, policy=export_policy), args.output)
        if args.html:
            _write(render_evidence_html(bundle), args.html)
        if args.junit:
            _write(evidence_to_junit(bundle), args.junit)
        # Fixture/replay success means the expected control was reproduced,
        # including a deliberately vulnerable control. Inspect only validates.
        return 0
    except (ValueError, TypeError, OSError, UnicodeError):
        # A malformed payload, path or exception can itself contain secrets.
        sys.stderr.write(
            "Evidence command failed: invalid, incompatible or unreadable input/output.\n"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
