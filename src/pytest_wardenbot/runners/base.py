"""AttackRunner Protocol.

Legacy boolean runner seam for chatbot integrations. Existing implementations
remain compatible. Instrumented agent trials use the separate
``pytest_wardenbot.agents.AgentTarget`` and ``RunResult`` contracts so missing
evidence and execution failures cannot collapse into boolean resistance.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from pytest_wardenbot.adapters.base import ChatbotAdapter


class AttackResult(BaseModel):
    """Legacy boolean result for chatbot runners.

    New agent integrations should use RunResult. The explicit
    ``agents.to_legacy_attack_result`` bridge only converts definite outcomes.
    """

    succeeded: bool = Field(
        description="True if the attack succeeded (i.e., the bot was vulnerable)."
    )
    summary: str = Field(description="Short human-readable summary of the outcome.")
    details: dict[str, object] | None = Field(
        default=None,
        description="Runner-specific structured details (turn transcripts, scores, etc.).",
    )


class AttackRunner(Protocol):
    """Protocol for attack runners.

    A runner takes a chatbot adapter and an attack goal (free-form string for now,
    structured in v0.2), executes an attack, and returns a structured result.
    """

    name: str
    """Short identifier for the runner, e.g. 'deterministic', 'pyrit-multiturn', 'rampart-xpia'."""

    def run(self, target: ChatbotAdapter, goal: str) -> AttackResult:
        """Run the attack against `target` with the given goal."""
        ...
