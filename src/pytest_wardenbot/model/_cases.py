"""Case names: which test a model request belongs to, and its folder name.

A case name keys everything the endpoint stores per test: response-folder
lookups, recordings, markers and canaries. It defaults to the running test's
id, the node id under pytest and ``self.id()`` under ``unittest`` and Django.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import re
import threading
import unittest

from pytest_wardenbot._errors import WardenBotConfigError

_PYTEST_PHASE = re.compile(r" \((?:setup|call|teardown)\)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_MAX_DIRNAME = 120

_pytest_sessions: set[int] = set()
_claimed: dict[str, str] = {}
_claimed_lock = threading.Lock()


def pytest_configured(session: object) -> None:
    """Called by the plugin when a pytest config is set up in this process."""
    _pytest_sessions.add(id(session))


def pytest_unconfigured(session: object) -> None:
    """Called by the plugin when that config is torn down.

    Keyed by config, so a teardown whose setup never ran (pytest unconfigures
    after a usage error in ``pytest_configure``) can't drop another session.
    """
    _pytest_sessions.discard(id(session))


def _pytest_case() -> str | None:
    # PYTEST_CURRENT_TEST is inherited by child processes, such as a Django test
    # run started from a pytest test, and `import pytest` alone proves nothing.
    # Only trust it while the plugin reports a pytest session in this process.
    if not _pytest_sessions:
        return None
    value = os.environ.get("PYTEST_CURRENT_TEST", "")
    return _PYTEST_PHASE.sub("", value) or None


def pytest_running() -> bool:
    """True while a pytest session runs in this process."""
    return bool(_pytest_sessions)


def running_test_id() -> str | None:
    """The running test's id (pytest node id, or unittest ``self.id()``), if any."""
    return _pytest_case() or _unittest_case()


def _unittest_case() -> str | None:
    frame = inspect.currentframe()
    try:
        while frame is not None:
            candidate = frame.f_locals.get("self")
            if isinstance(candidate, unittest.TestCase):
                return candidate.id()
            frame = frame.f_back
    finally:
        del frame
    return None


def current_case(explicit: str | None = None) -> str:
    """Return the case name: ``explicit``, else the running test's id.

    Raises ``WardenBotConfigError`` outside a test, asking for ``case=``.
    """
    if explicit is not None:
        if not explicit.strip():
            raise WardenBotConfigError("A wardenbot model case name cannot be empty.")
        return explicit
    case = _pytest_case() or _unittest_case()
    if case is None:
        raise WardenBotConfigError(
            "Cannot tell which test is running, so the model request has no case name. "
            "Pass one explicitly, for example model_endpoint(case='source_rating_attack')."
        )
    return case


def case_dirname(case: str) -> str:
    """Make a case name safe to use as one folder name.

    Characters outside ``[A-Za-z0-9_.-]`` become ``_``. Names made only of dots
    (``.`` and ``..``) can't escape the response folder, and names longer than
    120 characters keep a prefix plus a hash of the full name.
    """
    name = _UNSAFE.sub("_", case)
    if not name.strip("."):
        name = name.replace(".", "_") or "_"
    if len(name) > _MAX_DIRNAME:
        digest = hashlib.sha256(case.encode("utf-8")).hexdigest()[:12]
        name = f"{name[:100]}-{digest}"
    return name


def claim_case_dirname(case: str) -> str:
    """Return ``case_dirname(case)``, refusing a name another case already maps to.

    Different case names can sanitize to the same folder name (``a/b`` and
    ``a_b``), and case-insensitive filesystems also merge ``test_A`` and
    ``test_a``. Two cases sharing a folder would read and overwrite each
    other's replies, so within a process the second one fails instead.
    """
    name = case_dirname(case)
    with _claimed_lock:
        owner = _claimed.setdefault(name.casefold(), case)
    if owner != case:
        raise WardenBotConfigError(
            f"The case names {owner!r} and {case!r} both map to the response folder name "
            f"{name!r}, so they would share replies. Give one of them an explicit, distinct "
            "name with model_endpoint(case=...)."
        )
    return name
