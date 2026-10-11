"""Execute the reference model/MCP loop with offline or explicitly live requests."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# The example folder is distributed alongside the wheel/source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from examples.mcp_agent.offline_model import OfflineModel
from examples.mcp_agent.pilot import run_pilot
from openai import AsyncOpenAI  # type: ignore[import-not-found]


def controls_succeeded(report: dict) -> bool:
    for row in report["trials"]:
        if row["outcome"] == "not_run" or row["task_succeeded"] is not True:
            return False
        if row["phase"] == "benign":
            if row["baseline_ok"] is not True:
                return False
        elif row["profile"] == "safe":
            if row["outcome"] != "resisted" or row["sink_effects"] != 0:
                return False
        elif row["outcome"] != "violated" or row["sink_effects"] < 1:
            return False
    return bool(report["trials"])


async def execute(args: argparse.Namespace) -> dict:
    if args.live:
        key = os.environ.get("OPENAI_API_KEY")
        if not key or not args.model:
            raise ValueError(
                "Live evaluation requires OPENAI_API_KEY in the environment and --model"
            )
        client = AsyncOpenAI(
            api_key=key, base_url="https://api.openai.com/v1", max_retries=0, timeout=15
        )
    else:
        client = OfflineModel().client()
    try:
        return await run_pilot(
            client,
            model=args.model or "offline-response-model",
            samples=args.samples,
            split=args.split,
            transport=args.transport,
            protocol=args.protocol,
            max_calls=args.max_calls,
            max_output_tokens=args.max_output_tokens,
            trial_timeout=args.timeout,
            campaign_timeout=args.campaign_timeout,
            max_turns=args.max_turns,
            reasoning_effort=None if args.reasoning == "omit" else args.reasoning,
            mode="live" if args.live else "offline",
        )
    finally:
        async with asyncio.timeout(5):
            await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make bounded billable model requests")
    parser.add_argument("--model", help="Explicit model ID; required with --live")
    parser.add_argument("--samples", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--split", choices=["all", "development", "holdout"], default="all")
    parser.add_argument("--transport", choices=["memory", "stdio", "http"], default="memory")
    parser.add_argument("--protocol", choices=["2025-11-25", "2026-07-28"], default="2026-07-28")
    parser.add_argument("--max-calls", type=int, default=64)
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--campaign-timeout", type=float, default=180)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument(
        "--reasoning", choices=["none", "low", "medium", "high", "xhigh", "omit"], default="none"
    )
    parser.add_argument("--output", type=Path, help="Write the content-minimized JSON report here")
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 128 or not 16 <= args.max_output_tokens <= 2048:
        parser.error("Call/output limits must be within 1..128 calls and 16..2048 tokens")
    try:
        report = asyncio.run(execute(args))
    except Exception:
        sys.stderr.write(
            "Reference agent setup or campaign failed; check configuration and dependencies.\n"
        )
        return 2
    serialized = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0 if controls_succeeded(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
