"""Evaluation runner for pytest-wardenbot.

Runs the bundled deterministic suite against each configured bot in
`bots.py` and writes per-bot + summary result files into
`scripts/evaluation/results/`.

Usage:

    cp scripts/evaluation/.env.example scripts/evaluation/.env
    $EDITOR scripts/evaluation/.env       # paste API keys
    python scripts/evaluation/run.py

Or specify a subset:

    WARDENBOT_EVAL_BOTS=openai-gpt-4o-mini python scripts/evaluation/run.py

The runner loads `.env` via `python-dotenv` if available; otherwise it
uses the parent environment. Install via `pip install python-dotenv` to
get the convenience load.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVAL_DIR = REPO_ROOT / "scripts" / "evaluation"
RESULTS_DIR = EVAL_DIR / "results"
CONFTEST_RUNNER = EVAL_DIR / "conftest_runner.py"


def _load_dotenv() -> None:
    """Best-effort .env load. Silently skipped if python-dotenv isn't installed."""
    env_path = EVAL_DIR / ".env"
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
    except ImportError:
        print(
            "[eval] python-dotenv not installed; relying on parent env vars. "
            "Install with: pip install python-dotenv"
        )
        return
    load_dotenv(env_path)


def _run_pytest_for_bot(bot_id: str) -> tuple[int, dict[str, list[dict]]]:
    """Run the shipped tests against the given bot. Returns (exit_code, results_by_module)."""
    print(f"\n[eval] === {bot_id} ===")
    work = REPO_ROOT / ".pytest-eval-work" / bot_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy(CONFTEST_RUNNER, work / "conftest.py")

    # Copy each shipped test module into the workdir so pytest discovers them
    # under our conftest (--pyargs collection won't apply this dir's conftest
    # to tests collected from the installed package path).
    import pytest_wardenbot.tests as shipped_tests_pkg

    shipped_tests_dir = Path(shipped_tests_pkg.__file__).parent
    for src in sorted(shipped_tests_dir.glob("test_*.py")):
        shutil.copy(src, work / src.name)

    report_json = RESULTS_DIR / f"{bot_id}.raw.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    existing_pp = os.environ.get("PYTHONPATH", "")
    pp = str(REPO_ROOT) + (os.pathsep + existing_pp if existing_pp else "")
    env = {
        **os.environ,
        "WARDENBOT_EVAL_CURRENT_BOT": bot_id,
        "PYTHONPATH": pp,
    }

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            ".",
            "-v",
            "--tb=no",
            "--rootdir",
            str(work),
            "--override-ini=testpaths=",
            "--json-report",
            f"--json-report-file={report_json}",
        ],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
    )
    print(proc.stdout[-2000:] if proc.stdout else "")
    if proc.returncode > 1 and not report_json.exists():
        print(f"[eval] pytest crashed for {bot_id} (rc={proc.returncode}):", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode, {}

    if not report_json.exists():
        print(
            f"[eval] {bot_id}: pytest-json-report missing — install with "
            "`pip install pytest-json-report` to capture per-test results."
        )
        return proc.returncode, {}

    raw = json.loads(report_json.read_text())
    by_module: dict[str, list[dict]] = defaultdict(list)
    for test in raw.get("tests", []):
        nodeid = test.get("nodeid", "")
        module = nodeid.split("::")[0]
        by_module[module].append(
            {
                "nodeid": nodeid,
                "outcome": test.get("outcome"),
                "duration": test.get("duration"),
            }
        )
    return proc.returncode, dict(by_module)


_CATEGORY_LABELS: dict[str, str] = {
    "test_prompt_injection.py": "Prompt injection",
    "test_system_prompt_leak.py": "System-prompt elicitation",
    "test_refusal_bypass.py": "Refusal bypass",
    "test_off_topic.py": "Off-topic deflection",
    "test_indirect_injection.py": "Indirect injection (XPIA)",
    "test_encoded_payloads.py": "Encoded-payload",
    "test_multi_turn.py": "Multi-turn jailbreak",
    "test_business_truth.py": "Business truth (user facts)",
    "test_canary_leak.py": "Canary leak (opt-in)",
    "test_semantic.py": "LLM-judge (opt-in)",
}


def _write_markdown_report(bot_id: str, by_module: dict[str, list[dict]]) -> None:
    lines = [f"# Evaluation results — {bot_id}\n"]
    lines.append("| Category | Tests | Passed | Failed | Skipped |")
    lines.append("|---|---|---|---|---|")
    for module, label in _CATEGORY_LABELS.items():
        entries = by_module.get(module, [])
        if not entries:
            continue
        counts = defaultdict(int)
        for e in entries:
            counts[e["outcome"]] += 1
        lines.append(
            f"| {label} | {len(entries)} | "
            f"{counts['passed']} | {counts['failed']} | {counts['skipped']} |"
        )
    lines.append("")
    lines.append("## Per-test detail")
    lines.append("")
    for module, label in _CATEGORY_LABELS.items():
        entries = by_module.get(module, [])
        if not entries:
            continue
        lines.append(f"### {label}\n")
        for e in entries:
            short = e["nodeid"].split("::", 1)[-1]
            mark = {"passed": "✓", "failed": "✗", "skipped": "·"}.get(e["outcome"], "?")
            lines.append(f"- {mark} `{short}`")
        lines.append("")
    (RESULTS_DIR / f"{bot_id}.md").write_text("\n".join(lines))


def _write_summary(all_results: dict[str, dict[str, list[dict]]]) -> None:
    lines = ["# Evaluation summary\n"]
    lines.append("| Bot | Passed | Failed | Skipped | Total |")
    lines.append("|---|---|---|---|---|")
    for bot_id, by_module in all_results.items():
        totals = defaultdict(int)
        for entries in by_module.values():
            for e in entries:
                totals[e["outcome"]] += 1
        total = totals["passed"] + totals["failed"] + totals["skipped"]
        lines.append(
            f"| `{bot_id}` | {totals['passed']} | {totals['failed']} | "
            f"{totals['skipped']} | {total} |"
        )
    lines.append("")
    lines.append("Per-bot detail in `<bot-id>.md` files in this directory.")
    (RESULTS_DIR / "SUMMARY.md").write_text("\n".join(lines))


def main() -> int:
    _load_dotenv()
    from scripts.evaluation.bots import select_bots

    bots = select_bots()
    print(f"[eval] Running against {len(bots)} bot(s): {[b.id for b in bots]}")

    all_results: dict[str, dict[str, list[dict]]] = {}
    for bot in bots:
        try:
            _, results = _run_pytest_for_bot(bot.id)
            all_results[bot.id] = results
            _write_markdown_report(bot.id, results)
        except Exception as exc:
            print(f"[eval] {bot.id} skipped: {exc}", file=sys.stderr)
            continue

    if all_results:
        _write_summary(all_results)
        print(f"\n[eval] Done. Results in {RESULTS_DIR.relative_to(REPO_ROOT)}/")
    else:
        print("[eval] No bots produced results.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
