"""Attack runner abstractions + the parallel async probe runner.

`AttackRunner` is the v0.1 Protocol stub (a RAMPART-backed runner for tool-using
agents lands in a later release, gated behind the `[agentic]` extra).
`run_probes` is the native-async parallel probe runner — fan a corpus out
against an `AsyncChatbotAdapter` concurrently.
"""

from pytest_wardenbot.runners.async_probe import ProbeResult, run_probes
from pytest_wardenbot.runners.base import AttackRunner

__all__ = ["AttackRunner", "ProbeResult", "run_probes"]
