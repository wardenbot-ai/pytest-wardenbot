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
import sys
import unittest

from pytest_wardenbot._errors import WardenBotConfigError

_PYTEST_PHASE = re.compile(r" \((?:setup|call|teardown)\)$")
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_MAX_DIRNAME = 120


def _pytest_case() -> str | None:
    # PYTEST_CURRENT_TEST is inherited by child processes, such as a Django test
    # run started from a pytest test. Only trust it while pytest runs here.
    if "_pytest.runner" not in sys.modules:
        return None
    value = os.environ.get("PYTEST_CURRENT_TEST", "")
    return _PYTEST_PHASE.sub("", value) or None


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
