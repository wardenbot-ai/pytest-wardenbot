"""Run four offline controls for each local application boundary pack."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pytest_wardenbot.agents import (
    CampaignCase,
    CampaignLimits,
    Outcome,
    PrivacyPolicy,
    RunLimits,
    TrialContext,
    TrialResources,
    campaign_to_dict,
    create_evidence_bundle,
    evidence_fingerprint,
    evidence_to_dict,
    run_campaign,
)
from pytest_wardenbot.agents.packs import (
    APPLICATION_PACKS,
    ApplicationHarness,
    ApplicationPack,
    ApplicationPackSpec,
    ScriptedApplicationTarget,
)

Behavior = Literal["resistant", "vulnerable", "no_exposure"]
Variant = Literal["attack", "benign"]
_CONTROLS: tuple[tuple[Variant, Behavior], ...] = (
    ("benign", "resistant"),
    ("attack", "vulnerable"),
    ("attack", "resistant"),
    ("attack", "no_exposure"),
)


@dataclass
class Owned:
    spec: ApplicationPackSpec
    variant: Variant
    behavior: Behavior
    harness: ApplicationHarness
    target: ScriptedApplicationTarget
    factory_closed: bool = False


def make_case(
    spec: ApplicationPackSpec, variant: Variant, behavior: Behavior, owned: dict[str, Owned]
) -> CampaignCase:
    identifier = f"{spec.scenario.id}.{variant}.{behavior}"

    @asynccontextmanager
    async def factory(context: TrialContext) -> AsyncIterator[TrialResources]:
        harness = ApplicationHarness(
            spec, variant=variant, enforce_boundaries=behavior != "vulnerable"
        )
        target = ScriptedApplicationTarget(harness, behavior=behavior)
        item = Owned(spec, variant, behavior, harness, target)
        owned[context.trial_id] = item
        try:
            yield TrialResources(target, harness.observe)
        finally:
            item.factory_closed = True

    return CampaignCase(identifier, spec.scenario, factory)


async def execute(*, include_synthetic_content: bool = False) -> dict:
    """No SDK or model calls; fresh stores and principals belong to each case."""
    owned: dict[str, Owned] = {}
    cases = [
        make_case(spec, variant, behavior, owned)
        for spec in APPLICATION_PACKS
        for variant, behavior in _CONTROLS
    ]
    campaign = await run_campaign(
        cases,
        limits=CampaignLimits(
            max_calls=200,
            max_turns=200,
            concurrency=4,
            timeout_seconds=30,
            cleanup_timeout_seconds=3,
        ),
        run_limits=RunLimits(max_turns=12, timeout_seconds=15, cleanup_timeout_seconds=3),
    )
    report = campaign_to_dict(campaign)
    report["mode"] = "offline_application_controls"
    report["control_expectations_satisfied"] = True
    privacy = PrivacyPolicy(include_content=include_synthetic_content)
    evidence = []
    for row, planned, public_row in zip(campaign.trials, cases, report["trials"], strict=True):
        if row.result is None:
            report["control_expectations_satisfied"] = False
            continue
        item = owned[row.result.trial_id]
        expected = (
            Outcome.INCONCLUSIVE
            if item.variant == "benign" or item.behavior == "no_exposure"
            else Outcome.VIOLATED
            if item.behavior == "vulnerable"
            else Outcome.RESISTED
        )
        expected_utility = item.behavior != "no_exposure" and not (
            item.spec.pack is ApplicationPack.APPROVAL
            and item.variant == "attack"
            and item.behavior == "vulnerable"
        )
        public_row["application_pack"] = item.spec.pack.value
        public_row["variant"] = item.variant
        public_row["behavior"] = item.behavior
        public_row["required_hooks"] = list(item.spec.required_hooks)
        public_row["observed_event_counts"] = dict(
            Counter(event.kind.value for event in row.result.events)
        )
        public_row["sessions_closed"] = not item.harness.snapshot()["session_ids"]
        report["control_expectations_satisfied"] &= (
            row.result.outcome is expected
            and row.result.task_succeeded is expected_utility
            and item.factory_closed
            and not item.harness.snapshot()["session_ids"]
        )
        bundle = create_evidence_bundle(
            row.result,
            planned.scenario,
            target_fingerprint=evidence_fingerprint("scripted.application.control.v1"),
            config_fingerprint=evidence_fingerprint(
                {
                    "variant": item.variant,
                    "behavior": item.behavior,
                    "enforce_boundaries": item.behavior != "vulnerable",
                    "campaign_limits": report["limits"],
                    "run_limits": {
                        "max_turns": row.result.limits.max_turns,
                        "timeout_seconds": row.result.limits.timeout_seconds,
                        "cleanup_timeout_seconds": row.result.limits.cleanup_timeout_seconds,
                    },
                }
            ),
            corpus_fingerprint=evidence_fingerprint(
                {
                    "pack": item.spec.pack.value,
                    "scenario_id": planned.scenario.id,
                    "scenario_version": planned.scenario.version,
                    "attack_payload": item.spec.attack_payload,
                    "expected_fact": item.spec.expected_fact,
                    "required_hooks": list(item.spec.required_hooks),
                }
            ),
            target_run=item.target.last_target_run,
            harness_trace=item.target.last_trace,
            capabilities=item.target.capabilities,
            privacy=privacy,
        )
        evidence.append(evidence_to_dict(bundle, policy=privacy))
    report["evidence_bundles"] = evidence
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write the JSON report instead of stdout")
    parser.add_argument(
        "--include-synthetic-content",
        action="store_true",
        help="Retain public fixture observations for deterministic offline regrading",
    )
    arguments = parser.parse_args()
    report = asyncio.run(execute(include_synthetic_content=arguments.include_synthetic_content))
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if arguments.output:
        arguments.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0 if report["control_expectations_satisfied"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
