"""Regression tests for the global corpus-parametrization hook.

The shipped corpus-driven tests are parametrized by a single global
`pytest_generate_tests` hook in `plugin.py`, keyed on the test function name.
This keeps them parametrized when imported into another module (the bundled
examples and `--wardenbot-quickstart` output) — a per-module hook would not
fire for imported tests, which previously caused `fixture 'prompt' not found`.
"""

from __future__ import annotations

from typing import Any

from pytest_wardenbot import plugin


class _RecordingMetafunc:
    """Minimal `Metafunc` stand-in: enough for the hook + the `resolve_corpus`
    default path (no override fixtures registered -> bundled corpus used)."""

    def __init__(self, func_name: str, fixturenames: list[str]) -> None:
        def _fn() -> None: ...

        _fn.__name__ = func_name
        self.function = _fn
        self.fixturenames = fixturenames
        self._arg2fixturedefs: dict[str, Any] = {}
        self.definition = None  # -> resolve_corpus falls back to the default corpus
        self.parametrize_calls: list[tuple[Any, list[Any]]] = []

    def parametrize(self, argnames: Any, argvalues: Any, ids: Any = None) -> None:
        self.parametrize_calls.append((argnames, list(argvalues)))


def test_global_hook_parametrizes_imported_jailbreak_test() -> None:
    mf = _RecordingMetafunc(
        "test_resists_jailbreak_compliance",
        fixturenames=["chatbot", "prompt", "attack_id"],
    )
    plugin.pytest_generate_tests(mf)  # type: ignore[arg-type]

    assert len(mf.parametrize_calls) == 1
    argnames, argvalues = mf.parametrize_calls[0]
    assert argnames == ("prompt", "attack_id")
    assert len(argvalues) >= 2  # parametrized over the multi-entry bundled corpus


def test_global_hook_parametrizes_wider_shape() -> None:
    mf = _RecordingMetafunc(
        "test_resists_encoded_payload",
        fixturenames=["chatbot", "prompt", "trigger_words", "attack_id"],
    )
    plugin.pytest_generate_tests(mf)  # type: ignore[arg-type]

    assert mf.parametrize_calls
    argnames, _ = mf.parametrize_calls[0]
    assert argnames == ("prompt", "trigger_words", "attack_id")


def test_global_hook_ignores_non_wardenbot_tests() -> None:
    mf = _RecordingMetafunc("test_some_user_test", fixturenames=["prompt"])
    plugin.pytest_generate_tests(mf)  # type: ignore[arg-type]
    assert mf.parametrize_calls == []


def test_global_hook_skips_when_corpus_params_not_requested() -> None:
    # A known shipped-test name, but the corpus params aren't in the signature
    # (e.g. the name was reused): no parametrization, and no error.
    mf = _RecordingMetafunc("test_resists_jailbreak_compliance", fixturenames=["chatbot"])
    plugin.pytest_generate_tests(mf)  # type: ignore[arg-type]
    assert mf.parametrize_calls == []


def test_corpus_registry_attack_id_is_last_entry() -> None:
    # `ids` uses entry[-1], so every corpus entry must end with its attack_id.
    for _params, _fixture, default_corpus in plugin._CORPUS_TESTS.values():
        assert default_corpus, "bundled corpus should be non-empty"
        assert all(isinstance(entry[-1], str) for entry in default_corpus)
