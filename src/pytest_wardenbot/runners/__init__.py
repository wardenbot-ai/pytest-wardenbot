"""Attack runner abstractions.

v0.1 ships the Protocol only. v0.2 will register concrete runners — including
a RAMPART-backed runner for tool-using agents, gated behind the `[agentic]` extra.
"""

from pytest_wardenbot.runners.base import AttackRunner

__all__ = ["AttackRunner"]
