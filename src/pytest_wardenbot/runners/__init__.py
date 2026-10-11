"""Attack runner abstractions + the parallel async probe runner.

`AttackRunner` is the compatible legacy boolean Protocol. Instrumented tool-using
agent trials live in `pytest_wardenbot.agents`; RAMPART remains separate roadmap work.
`run_probes` is the native-async parallel probe runner — fan a corpus out
against an `AsyncChatbotAdapter` concurrently.
"""

from pytest_wardenbot.runners.async_probe import ProbeResult, run_probes
from pytest_wardenbot.runners.base import AttackRunner

__all__ = ["AttackRunner", "ProbeResult", "run_probes"]
