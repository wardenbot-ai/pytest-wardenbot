"""Smoke tests for the AttackRunner adapter pattern.

v0.1 ships the Protocol stub only; concrete runners (PyRIT, RAMPART, etc.) land
in v0.2. These tests confirm the public API surface exists and is usable.
"""

from __future__ import annotations

from pytest_wardenbot.adapters.base import ChatbotResponse
from pytest_wardenbot.runners import AttackRunner
from pytest_wardenbot.runners.base import AttackResult


def test_attack_runner_protocol_importable() -> None:
    """The Protocol must be importable from the package surface."""
    assert AttackRunner is not None


def test_attack_result_basic_construction() -> None:
    result = AttackResult(succeeded=False, summary="ok")
    assert result.succeeded is False
    assert result.summary == "ok"
    assert result.details is None


def test_attack_result_with_details() -> None:
    result = AttackResult(
        succeeded=True,
        summary="leaked",
        details={"matched": ["pattern1"], "turns": 3},
    )
    assert result.succeeded is True
    assert result.details == {"matched": ["pattern1"], "turns": 3}


def test_user_can_implement_attack_runner_protocol() -> None:
    """A small runner class satisfies the Protocol contract."""

    class StubRunner:
        name = "stub"

        def run(self, target: object, goal: str) -> AttackResult:
            del target
            return AttackResult(succeeded=False, summary=f"would attack with goal={goal!r}")

    runner: AttackRunner = StubRunner()
    result = runner.run(target=None, goal="test")
    assert result.succeeded is False
    assert "test" in result.summary


def test_chatbot_response_with_no_raw_or_latency() -> None:
    """Cover the default-None branches of ChatbotResponse."""
    response = ChatbotResponse(text="hi")
    assert response.text == "hi"
    assert response.raw is None
    assert response.latency_ms is None
