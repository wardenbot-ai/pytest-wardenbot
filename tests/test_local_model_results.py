"""The preregistered local-model analysis computes what the page says it does."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from scripts.evaluation.local_models import SAMPLES, analyze, render, wilson


def test_wilson_interval_matches_known_values():
    low, high = wilson(6, 20)  # type: ignore[misc]
    assert round(low, 3) == 0.145 and round(high, 3) == 0.519
    assert wilson(0, 20) == (0.0, pytest.approx(0.161, abs=1e-3))
    assert wilson(20, 20)[1] == 1.0  # type: ignore[index]
    assert wilson(0, 0) is None


def row(model, surface, phase, outcome, *, pack="mcp", exposure="delivered", task=True):
    return {
        "model": model,
        "surface": surface,
        "pack": pack,
        "phase": phase,
        "outcome": outcome,
        "exposure": exposure,
        "task_succeeded": task,
    }


def test_analysis_reports_primary_and_secondary_rates():
    rows = [
        row("m", "tool_result", "attack", "violated"),
        row("m", "tool_result", "attack", "violated"),
        row("m", "tool_result", "attack", "resisted"),
        row("m", "tool_result", "attack", "inconclusive", exposure="not_observed"),
        row("m", "tool_result", "attack", "error", exposure="not_observed"),
        row("m", "tool_result", "baseline", "inconclusive", exposure="not_observed"),
        row("m", "tool_result", "baseline", "violated", exposure="not_observed", task=False),
        row("m", "input_request", "attack", "resisted", pack="lifecycle"),
        row("m", "input_request", "baseline", "inconclusive", pack="lifecycle"),
    ]
    summary = analyze(rows)["models"]["m"]
    attack = summary["tool_result"]["attack"]
    assert attack["outcomes"] == {"error": 1, "inconclusive": 1, "resisted": 1, "violated": 2}
    # Primary: decided trials only. Secondary: every planned trial.
    assert attack["attack_success_exposed"]["successes"] == 2
    assert attack["attack_success_exposed"]["trials"] == 3
    assert attack["attack_success_all"]["trials"] == 5
    assert attack["exposure"]["successes"] == 3
    baseline = summary["tool_result"]["baseline"]
    assert baseline["unprompted_violation"]["successes"] == 1
    assert baseline["task_success"]["successes"] == 1
    assert summary["all_default"]["attack"]["trials"] == 5
    assert summary["all_lifecycle"]["attack"]["attack_success_exposed"]["successes"] == 0
    table = render(analyze(rows))
    assert "| `tool_result` | 2/3 (67%; 95% CI" in table
    assert "**Lifecycle pack (4 scenarios)**" in table


def test_registered_sample_size():
    assert SAMPLES == 10


RESULTS = Path(__file__).resolve().parents[1] / "docs" / "about" / "local-model-results"


@pytest.mark.skipif(not (RESULTS / "rows.jsonl").exists(), reason="results not published yet")
def test_published_tables_match_the_published_rows():
    rows = [json.loads(line) for line in (RESULTS / "rows.jsonl").read_text().splitlines()]
    run = json.loads((RESULTS / "run.json").read_text())
    page = (RESULTS.parent / "local-model-results.md").read_text(encoding="utf-8")
    # Every planned trial is present exactly once: no reruns, drops or extras.
    planned = {
        (model, scenario, phase, sample)
        for model in run["models"]
        for scenario in {row["scenario"] for row in rows}
        for phase in ("baseline", "attack")
        for sample in range(run["samples"])
    }
    assert len(rows) == len(planned) == 480
    assert {(r["model"], r["scenario"], r["phase"], r["sample"]) for r in rows} == planned
    # The page shows exactly what the registered analysis computes, per model.
    tables = render(analyze(rows))
    blocks = [block.strip() for block in tables.split("### ")[1:]]
    assert len(blocks) == len(run["models"])
    for block in blocks:
        assert "### " + block in page
    with gzip.open(RESULTS / "evidence.jsonl.gz", "rt") as stream:
        assert sum(1 for _ in stream) == len(rows)
