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
"""

from __future__ import annotations

import inspect
from collections.abc import Sequence
from typing import Any

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

    Both are internal pytest APIs but they've been stable across 7.x and 8.x
    and are used by other plugins (pytest-asyncio, pytest-bdd, etc).
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

    defs = fm.getfixturedefs(fixture_name, definition)
    return defs or ()


def resolve_corpus(
    metafunc: Any,
    fixture_name: str,
    default_corpus: Sequence[CorpusEntry],
) -> Sequence[CorpusEntry]:
    """Look up `fixture_name` in the active fixture chain; return its value or default.

    Walks the fixture defs from most-specific to most-generic and returns the
    first fixture function value that's callable with zero args. Falls back to
    `default_corpus` if no usable override is registered.
    """
    fixturedefs = _lookup_fixture_defs(metafunc, fixture_name)
    if not fixturedefs:
        return default_corpus

    for fixturedef in reversed(fixturedefs):
        func = getattr(fixturedef, "func", None)
        if func is None:
            continue
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            continue
        if sig.parameters:
            # Fixture has dependencies we can't satisfy at collection time.
            continue
        try:
            value = func()
        except Exception:
            continue
        if value is None:
            continue
        return tuple(value)

    return default_corpus
