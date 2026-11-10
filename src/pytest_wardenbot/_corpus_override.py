"""Resolve user-supplied corpus overrides at collection time.

Each shipped test that parametrizes over an attack corpus uses
`pytest_generate_tests` to look up an override fixture (e.g.
`wardenbot_jailbreak_prompts`). If the user has registered such a fixture in
their conftest.py, the override is used; otherwise the bundled default applies.

The override fixture must be a plain `() -> tuple[(str, str), ...]` function —
no `request`, no other fixture dependencies. That's because pytest's
fixture machinery isn't fully available at collection time; we call the
fixture function directly. If the override needs more setup, the user should
build their corpus at import time and have the fixture return the prepared
tuple.

An override that cannot be used (it takes parameters, raises, or returns
None or a non-iterable) raises `WardenBotConfigError` instead of silently
falling back to the bundled corpus: a security run must not test something
other than what was configured.
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any

from pytest_wardenbot._errors import WardenBotConfigError

_PLUGIN_MODULE = "pytest_wardenbot.plugin"

# Different corpora have different entry shapes (jailbreak: (prompt, attack_id),
# encoded: (prompt, triggers, attack_id), multi-turn: (priming, payload, attack_id)).
# We keep the type loose here — each shipped test knows its own entry shape.
CorpusEntry = tuple[Any, ...]


def _lookup_fixture_defs(metafunc: Any, fixture_name: str) -> Sequence[Any]:
    """Return all fixture defs for `fixture_name` visible to the test node.

    Two sources are consulted:

    1. `metafunc._arg2fixturedefs` — fixtures already in the test's argument
       closure. Hit when the test function (or some other fixture it depends
       on) declares the corpus-override fixture as a param.

    2. `config._fixturemanager.getfixturedefs(fixture_name, metafunc.definition)`
       — full conftest chain lookup. Hit in the common case where the user
       defines `wardenbot_jailbreak_prompts` in their conftest but the test
       function doesn't list it as a param.

    Both are internal pytest APIs. The supported pytest range is exercised by
    integration tests with external consumer fixtures.
    """
    closure_defs = getattr(metafunc, "_arg2fixturedefs", {}).get(fixture_name)
    if closure_defs:
        return closure_defs

    # Common case: the test function doesn't list the override fixture as a
    # parameter, so it's not in the test's closure. Look it up via the session's
    # FixtureManager — that's where every registered fixture (plugin defaults +
    # user conftest overrides) lives.
    #
    # In pytest 8.x the FixtureManager was reachable as `config._fixturemanager`;
    # in 9.x it lives on the Session. We try both for compatibility.
    definition = getattr(metafunc, "definition", None)
    if definition is None:
        return ()
    fm = None
    session = getattr(definition, "session", None)
    if session is not None:
        fm = getattr(session, "_fixturemanager", None)
    if fm is None:
        config = getattr(metafunc, "config", None)
        if config is not None:
            fm = getattr(config, "_fixturemanager", None)
    if fm is None:
        return ()

    # Supported pytest versions (8.1.1+) expect a Node here, not a nodeid.
    defs = fm.getfixturedefs(fixture_name, definition)
    return defs or ()


def resolve_corpus(
    metafunc: Any,
    fixture_name: str,
    default_corpus: Sequence[CorpusEntry],
) -> Sequence[CorpusEntry]:
    """Look up `fixture_name` in the active fixture chain; return its value or default.

    The most specific fixture wins. The plugin's own default returns
    `default_corpus`; any other (user) override must be usable or this raises
    `WardenBotConfigError`.
    """
    fixturedefs = _lookup_fixture_defs(metafunc, fixture_name)
    if not fixturedefs:
        return default_corpus

    for fixturedef in reversed(fixturedefs):
        func = getattr(fixturedef, "func", None)
        if func is None:
            continue
        if getattr(func, "__module__", None) == _PLUGIN_MODULE:
            # The bundled default: nothing more specific overrides it.
            return default_corpus
        return _read_override(fixture_name, func)

    return default_corpus


def _read_override(fixture_name: str, func: Any) -> tuple[CorpusEntry, ...]:
    where = f"{getattr(func, '__module__', '?')}.{getattr(func, '__qualname__', fixture_name)}"
    try:
        parameters = list(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        parameters = []
    if parameters:
        raise WardenBotConfigError(
            f"The `{fixture_name}` override ({where}) takes parameters ({', '.join(parameters)}). "
            "Corpus overrides are read at collection time and must take no arguments: build "
            "the corpus at import time and have the fixture return it."
        )
    try:
        value = func()
    except Exception as exc:
        raise WardenBotConfigError(
            f"The `{fixture_name}` override ({where}) raised {type(exc).__name__} while the "
            "corpus was being read at collection time."
        ) from exc
    if value is None:
        raise WardenBotConfigError(
            f"The `{fixture_name}` override ({where}) returned None. Return a tuple of corpus "
            "entries, or () to collect no cases."
        )
    try:
        return tuple(value)
    except TypeError as exc:
        raise WardenBotConfigError(
            f"The `{fixture_name}` override ({where}) returned {type(value).__name__}, not an "
            "iterable of corpus entries."
        ) from exc
