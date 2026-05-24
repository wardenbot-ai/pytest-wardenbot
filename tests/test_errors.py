"""Tests for the pytest-wardenbot error taxonomy."""

from __future__ import annotations

from pytest_wardenbot import WardenBotError, WardenBotInfraError


def test_infra_error_is_warden_bot_error() -> None:
    assert issubclass(WardenBotInfraError, WardenBotError)


def test_warden_bot_error_is_exception() -> None:
    assert issubclass(WardenBotError, Exception)


def test_infra_error_preserves_cause() -> None:
    original = ValueError("original failure")
    try:
        try:
            raise original
        except ValueError as exc:
            raise WardenBotInfraError("wrapped") from exc
    except WardenBotInfraError as wrapped:
        assert wrapped.__cause__ is original


def test_warden_bot_error_catches_infra_error() -> None:
    """Users who want to catch any wardenbot-raised error can use the base class."""
    try:
        raise WardenBotInfraError("boom")
    except WardenBotError as exc:
        assert "boom" in str(exc)
