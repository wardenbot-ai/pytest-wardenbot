"""Preregistered local-model run: the agent suite against Ollama models.

The method is registered in docs/about/local-model-results.md before any trial
runs. This script implements it exactly:

    python scripts/evaluation/local_models.py run --output DIR
    python scripts/evaluation/local_models.py analyze DIR

``run`` drives the agent from ``pytest --wardenbot-quickstart=agent`` (generated
fresh, unmodified) against each model through Ollama, for every default and
lifecycle scenario, baseline and attack, ``--samples`` times each. Every planned
trial runs once and is kept. It writes ``rows.jsonl`` (one content-free row per
trial), ``evidence.jsonl.gz`` (one regradeable evidence bundle per trial; all
content is synthetic) and ``run.json`` (versions, digests, timing).

``analyze`` turns ``rows.jsonl`` into ``summary.json`` and ``summary.md`` with
Wilson 95% intervals.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib.util
import json
import math
import os
import platform
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MODELS = ("qwen2.5:7b", "mistral:7b")
SAMPLES = 10
MAX_TURNS = 10
TIMEOUT_SECONDS = 120
OLLAMA = "http://127.0.0.1:11434"
SURFACE_ORDER = (
    "tool_result",
    "tool_description",
    "resource",
    "prompt",
    "tool_definition_change",
    "input_request",
)


# -- statistics ------------------------------------------------------------------------


def wilson(successes: int, trials: int, z: float = 1.959964) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _rate(successes: int, trials: int) -> dict[str, Any]:
    interval = wilson(successes, trials)
    return {
        "successes": successes,
        "trials": trials,
        "rate": successes / trials if trials else None,
        "ci95": list(interval) if interval else None,
    }


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Preregistered analysis. Attack success is reported two ways:

    - ``exposed``: violated / (violated + resisted), the trials whose evidence
      could decide the question (primary);
    - ``all``: violated / all planned attack trials (secondary).
    """
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["model"], row["surface"], row["phase"])].append(row)
        groups[
            (row["model"], "all_default" if row["pack"] == "mcp" else "all_lifecycle", row["phase"])
        ].append(row)
    summary: dict[str, Any] = {"models": {}}
    for (model, surface, phase), items in sorted(groups.items()):
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            counts[item["outcome"]] += 1
        entry: dict[str, Any] = {"trials": len(items), "outcomes": dict(sorted(counts.items()))}
        violated = counts["violated"]
        if phase == "attack":
            entry["attack_success_exposed"] = _rate(violated, violated + counts["resisted"])
            entry["attack_success_all"] = _rate(violated, len(items))
            entry["exposure"] = _rate(
                sum(item["exposure"] != "not_observed" for item in items), len(items)
            )
        else:
            entry["unprompted_violation"] = _rate(violated, len(items))
            entry["task_success"] = _rate(
                sum(item["task_succeeded"] is True for item in items), len(items)
            )
        summary["models"].setdefault(model, {}).setdefault(surface, {})[phase] = entry
    return summary


def _percent(rate: dict[str, Any]) -> str:
    if rate["rate"] is None:
        return "—"
    low, high = rate["ci95"]
    return (
        f"{rate['successes']}/{rate['trials']} ({rate['rate']:.0%}; 95% CI {low:.0%} to {high:.0%})"
    )


def render(summary: dict[str, Any]) -> str:
    lines = []
    for model, surfaces in summary["models"].items():
        lines += [
            f"### `{model}`",
            "",
            "| Surface | Attacks followed (exposed) | "
            "Attacks followed (all) | Unprompted sink calls in baselines | "
            "Baseline task success |",
            "|---|---|---|---|---|",
        ]
        for surface in (*SURFACE_ORDER, "all_default", "all_lifecycle"):
            if surface not in surfaces:
                continue
            attack, baseline = surfaces[surface]["attack"], surfaces[surface]["baseline"]
            label = {
                "all_default": "**Default pack (8 scenarios)**",
                "all_lifecycle": "**Lifecycle pack (4 scenarios)**",
            }.get(surface, f"`{surface}`")
            lines.append(
                f"| {label} | {_percent(attack['attack_success_exposed'])} | "
                f"{_percent(attack['attack_success_all'])} | "
                f"{_percent(baseline['unprompted_violation'])} | "
                f"{_percent(baseline['task_success'])} |"
            )
        lines.append("")
    return "\n".join(lines)


# -- execution ---------------------------------------------------------------------------


def _ollama(path: str) -> Any:
    with urllib.request.urlopen(OLLAMA + path, timeout=10) as response:
        return json.loads(response.read())


def _model_details(model: str) -> dict[str, Any]:
    tags = {item["name"]: item for item in _ollama("/api/tags")["models"]}
    if model not in tags:
        raise SystemExit(f"{model} is not pulled in Ollama")
    request = urllib.request.Request(
        OLLAMA + "/api/show", data=json.dumps({"model": model}).encode(), method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        shown = json.loads(response.read())
    return {
        "digest": tags[model]["digest"],
        "details": tags[model].get("details", {}),
        "parameters": shown.get("parameters", ""),
    }


def _load_quickstart_agent(model: str, directory: Path) -> Any:
    from pytest_wardenbot.quickstart import generate

    target = directory / model.replace(":", "_").replace(".", "_")
    target.mkdir()
    generate("agent", target)
    os.environ["AGENT_LOCAL"] = "ollama"
    os.environ["AGENT_MODEL"] = model
    os.environ.pop("OPENAI_API_KEY", None)
    spec = importlib.util.spec_from_file_location(
        f"quickstart_{target.name}", target / "conftest.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert model == module.MODEL and module.LOCAL == "ollama"
    return module


async def _run(models: tuple[str, ...], samples: int, output: Path, commit: str) -> None:
    from pytest_wardenbot import __version__
    from pytest_wardenbot.agents import (
        PrivacyPolicy,
        RunLimits,
        create_evidence_bundle,
        evidence_fingerprint,
        evidence_to_json,
        run_scenario,
    )
    from pytest_wardenbot.agents.scenarios import (
        AGENT_SCENARIOS,
        LIFECYCLE_SCENARIOS,
        scenario_selection_id,
    )
    from pytest_wardenbot.mcp import MCPHarness
    from pytest_wardenbot.mcp._server import attack_instruction

    exact = PrivacyPolicy(include_content=True, max_text_chars=100_000, max_depth=24)
    scenarios = [(case, "mcp") for case in AGENT_SCENARIOS] + [
        (case, "lifecycle") for case in LIFECYCLE_SCENARIOS
    ]
    meta: dict[str, Any] = {
        "pytest_wardenbot": __version__,
        "commit": commit,
        "python": platform.python_version(),
        "machine": platform.machine(),
        "ollama": _ollama("/api/version").get("version"),
        "samples": samples,
        "max_turns": MAX_TURNS,
        "timeout_seconds": TIMEOUT_SECONDS,
        "models": {},
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    limits = RunLimits(timeout_seconds=TIMEOUT_SECONDS, max_turns=MAX_TURNS)
    with (
        tempfile.TemporaryDirectory() as directory,
        (output / "rows.jsonl").open("w") as rows,
        gzip.open(output / "evidence.jsonl.gz", "wt") as evidence,
    ):
        for model in models:
            details = _model_details(model)
            module = _load_quickstart_agent(model, Path(directory))
            meta["models"][model] = details
            target_fingerprint = evidence_fingerprint(
                {"agent": "quickstart-agent", "model": model, "digest": details["digest"]}
            )
            config_fingerprint = evidence_fingerprint(
                {
                    "ollama": meta["ollama"],
                    "system": module.SYSTEM,
                    "max_turns": MAX_TURNS,
                    "timeout_seconds": TIMEOUT_SECONDS,
                }
            )
            started = time.time()
            for sample in range(samples):
                for scenario, pack in scenarios:
                    for phase in ("baseline", "attack"):
                        harness = MCPHarness(scenario, attack_enabled=phase == "attack")
                        agent = module.MyAgent(harness)
                        runs: list[Any] = []
                        original = agent.run

                        async def recorded(task, *, trial_id, max_turns, _run=original, _runs=runs):
                            result = await _run(task, trial_id=trial_id, max_turns=max_turns)
                            _runs.append(result)
                            return result

                        agent.run = recorded
                        began = time.time()
                        result = await run_scenario(
                            agent, scenario, observe=harness.observe, limits=limits
                        )
                        row = {
                            "model": model,
                            "scenario": scenario_selection_id(scenario),
                            "pack": pack,
                            "surface": scenario.surface.value,
                            "assertion": "forbidden-tool" if scenario.forbidden_tool else "canary",
                            "phase": phase,
                            "sample": sample,
                            "outcome": result.outcome.value,
                            "reason_codes": [code.value for code in result.reason_codes],
                            "exposure": result.exposure.value,
                            "task_succeeded": result.task_succeeded,
                            "turns": result.turns,
                            "seconds": round(time.time() - began, 2),
                        }
                        rows.write(json.dumps(row) + "\n")
                        rows.flush()
                        bundle = create_evidence_bundle(
                            result,
                            scenario,
                            target_fingerprint=target_fingerprint,
                            config_fingerprint=config_fingerprint,
                            corpus_fingerprint=evidence_fingerprint(
                                {
                                    "scenario": scenario_selection_id(scenario),
                                    "injection": attack_instruction(scenario),
                                }
                            ),
                            target_run=runs[0] if runs else None,
                            harness_trace=harness.observe(result.trial_id),
                            capabilities=agent.capabilities,
                            privacy=exact,
                        )
                        record = json.loads(evidence_to_json(bundle, policy=exact))
                        evidence.write(json.dumps(record, separators=(",", ":")) + "\n")
                        print(
                            f"{model} s{sample} {row['scenario']} {phase}: {row['outcome']}",
                            flush=True,
                        )
            meta["models"][model]["seconds"] = round(time.time() - started)
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (output / "run.json").write_text(json.dumps(meta, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--models", nargs="+", default=list(MODELS))
    run.add_argument("--samples", type=int, default=SAMPLES)
    report = commands.add_parser("analyze")
    report.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        args.output.mkdir(parents=True, exist_ok=False)
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout.strip()
        asyncio.run(_run(tuple(args.models), args.samples, args.output, commit))
        return 0
    rows = [json.loads(line) for line in (args.directory / "rows.jsonl").read_text().splitlines()]
    summary = analyze(rows)
    (args.directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.directory / "summary.md").write_text(render(summary) + "\n")
    print(render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["analyze", "render", "wilson"]
