"""Parallel async probe runner.

The shipped tests send one prompt per test and run serially. Against a real bot
that serialization dominates wall-clock time — a 29-probe suite at ~1s/call is
~29s. `run_probes` fans the whole batch out concurrently against an
`AsyncChatbotAdapter` (bounded by a semaphore so you don't blow past rate
limits) and returns per-prompt results **in input order**, which you then grade
with the same deterministic helpers (`assert_no_jailbreak_compliance`, etc.).

This is the native-async counterpart to the sync shipped tests: instead of
bundling `@pytest.mark.asyncio` tests into the discoverable suite (which would
force `pytest-asyncio` on every user under `--strict-markers` and risk silent
false-passes when no async plugin is active), wardenbot ships the runner and a
recipe — you write one async test that awaits it. See the "Run probes in
parallel" how-to.

A send that raises `WardenBotInfraError` (unreachable / malformed bot) is
captured in that probe's `ProbeResult.error` rather than sinking the whole
batch — inspect `.error` / `.ok` and decide how to surface it. Other exceptions
propagate (a real bug should not be swallowed).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.base import AsyncChatbotAdapter, ChatbotResponse


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of one probe in a parallel batch."""

    attack_id: str
    """The corpus entry's id (echoed for correlating results back to prompts)."""

    prompt: str
    """The prompt that was sent."""

    response: ChatbotResponse | None
    """The chatbot's response, or `None` if the send raised an infra error."""

    error: WardenBotInfraError | None
    """The captured `WardenBotInfraError`, or `None` if the send succeeded."""

    @property
    def ok(self) -> bool:
        """True if the send succeeded (a response is available to grade)."""
        return self.error is None


async def run_probes(
    adapter: AsyncChatbotAdapter,
    prompts: Sequence[tuple[str, str]],
    *,
    concurrency: int = 5,
) -> list[ProbeResult]:
    """Send every `(prompt, attack_id)` concurrently, bounded by `concurrency`.

    Args:
        adapter: the async chatbot adapter under test.
        prompts: `(prompt, attack_id)` pairs. For corpora with wider shapes
            (encoded-payload / indirect injection are `(prompt, trigger_words,
            attack_id)`), pass `[(p, aid) for p, _, aid in CORPUS]`. Multi-turn
            corpora are sequential, not a single-send fan-out — drive those with
            the sync multi-turn test instead.
        concurrency: max sends in flight at once (default 5). Tune to your bot's
            rate limit.

    Returns:
        `ProbeResult`s in the same order as `prompts`. Infra errors are captured
        per-probe (see `ProbeResult.error` / `.ok`), not raised.
    """
    if concurrency < 1:
        raise ValueError("concurrency must be >= 1")
    semaphore = asyncio.Semaphore(concurrency)

    async def _probe(prompt: str, attack_id: str) -> ProbeResult:
        async with semaphore:
            try:
                response = await adapter.send_message(prompt)
            except WardenBotInfraError as exc:
                return ProbeResult(attack_id=attack_id, prompt=prompt, response=None, error=exc)
            return ProbeResult(attack_id=attack_id, prompt=prompt, response=response, error=None)

    return list(await asyncio.gather(*(_probe(prompt, attack_id) for prompt, attack_id in prompts)))
