"""Tests for the corpus-override resolution helper used by pytest_generate_tests."""

from __future__ import annotations

from typing import Any

import pytest

from pytest_wardenbot import WardenBotConfigError
from pytest_wardenbot._corpus_override import resolve_corpus

DEFAULT = (("a", "id-a"), ("b", "id-b"))


class _FakeFixtureDef:
    def __init__(self, func: Any) -> None:
        self.func = func


class _FakeMetafunc:
    def __init__(self, fixturedefs_by_name: dict[str, list[_FakeFixtureDef]]) -> None:
        self._arg2fixturedefs = fixturedefs_by_name


def test_returns_default_when_no_fixture_registered() -> None:
    metafunc = _FakeMetafunc({})
    assert resolve_corpus(metafunc, "wardenbot_anything", DEFAULT) == DEFAULT


def test_returns_default_when_fixture_chain_empty() -> None:
    metafunc = _FakeMetafunc({"wardenbot_anything": []})
    assert resolve_corpus(metafunc, "wardenbot_anything", DEFAULT) == DEFAULT


def test_returns_override_value_when_user_fixture_present() -> None:
    custom = (("x", "id-x"),)

    def user_fixture() -> tuple[tuple[str, str], ...]:
        return custom

    metafunc = _FakeMetafunc({"wardenbot_anything": [_FakeFixtureDef(user_fixture)]})
    assert resolve_corpus(metafunc, "wardenbot_anything", DEFAULT) == custom


def test_user_override_wins_over_plugin_default() -> None:
    def plugin_default() -> tuple[tuple[str, str], ...]:
        return DEFAULT

    def user_override() -> tuple[tuple[str, str], ...]:
        return (("user", "id-user"),)

    # Chain order: most-generic first (plugin), most-specific last (user conftest).
    metafunc = _FakeMetafunc(
        {
            "wardenbot_anything": [
                _FakeFixtureDef(plugin_default),
                _FakeFixtureDef(user_override),
            ]
        }
    )
    result = resolve_corpus(metafunc, "wardenbot_anything", DEFAULT)
    assert result == (("user", "id-user"),)


def _plugin_default() -> tuple[tuple[str, str], ...]:
    return DEFAULT


_plugin_default.__module__ = "pytest_wardenbot.plugin"


def test_plugin_default_alone_returns_the_bundled_corpus() -> None:
    metafunc = _FakeMetafunc({"wardenbot_anything": [_FakeFixtureDef(_plugin_default)]})
    assert resolve_corpus(metafunc, "wardenbot_anything", DEFAULT) == DEFAULT


def test_override_with_dependencies_is_a_configuration_error() -> None:
    def needs_request(request: Any) -> tuple[tuple[str, str], ...]:
        del request
        return (("never", "called"),)

    metafunc = _FakeMetafunc(
        {"wardenbot_anything": [_FakeFixtureDef(_plugin_default), _FakeFixtureDef(needs_request)]}
    )
    with pytest.raises(WardenBotConfigError, match="takes parameters \\(request\\)"):
        resolve_corpus(metafunc, "wardenbot_anything", DEFAULT)


def test_override_that_raises_is_a_configuration_error() -> None:
    def broken() -> tuple[tuple[str, str], ...]:
        raise RuntimeError("can't compute corpus")

    metafunc = _FakeMetafunc({"wardenbot_anything": [_FakeFixtureDef(broken)]})
    with pytest.raises(WardenBotConfigError, match="raised RuntimeError") as exc_info:
        resolve_corpus(metafunc, "wardenbot_anything", DEFAULT)
    assert isinstance(exc_info.value.__cause__, RuntimeError)


@pytest.mark.parametrize(("value", "message"), [(None, "returned None"), (42, "returned int")])
def test_override_returning_none_or_non_iterable_is_a_configuration_error(
    value: object, message: str
) -> None:
    def returns_value() -> object:
        return value

    metafunc = _FakeMetafunc({"wardenbot_anything": [_FakeFixtureDef(returns_value)]})
    with pytest.raises(WardenBotConfigError, match=message):
        resolve_corpus(metafunc, "wardenbot_anything", DEFAULT)


def test_supports_empty_override_corpus() -> None:
    """Returning an empty corpus is a valid override (parametrize collects 0 tests)."""

    def empty() -> tuple[tuple[str, str], ...]:
        return ()

    metafunc = _FakeMetafunc({"wardenbot_anything": [_FakeFixtureDef(empty)]})
    assert resolve_corpus(metafunc, "wardenbot_anything", DEFAULT) == ()
