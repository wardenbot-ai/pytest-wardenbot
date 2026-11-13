"""Injection markers and canaries that stay the same per case across runs.

A marker is planted in untrusted test input and searched for in the output. In
``record``, ``replay`` and ``override`` it is derived from the case name and the
response folder's ``marker_seed`` with HMAC-SHA256, so a recorded reply carries
the same marker the replaying test plants and looks for: request hashes match,
and ``.sse`` files replay byte for byte with no substitution. In the other
modes markers are random, but stable per case within a process.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import os
import secrets
import tempfile
import threading
import time
import tomllib
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pytest_wardenbot.canary import CANARY_PREFIX, generate_canary_token
from pytest_wardenbot.model._cases import current_case
from pytest_wardenbot.model._errors import ModelEndpointError

MARKER_PREFIX = "WBMARK-"
"""Prefix of every injection marker, so a leaked marker is easy to grep for."""

MANIFEST_NAME = "wardenbot-responses.toml"
DEFAULT_SEED = "wardenbot"
SEEDED_MODES = frozenset({"record", "replay", "override"})

_lock = threading.Lock()
_random: dict[tuple[str, str], str] = {}
_seed_cache: dict[Path, tuple[tuple[int, int], str | None]] = {}
_LOCK_TIMEOUT_SECONDS = 30.0
_warned_default_seed = False


def _endpoint_state() -> tuple[str | None, Path | None, Any]:
    """The global mode, the response folder and the active block, if any."""
    from pytest_wardenbot.model._endpoint import current_endpoint

    endpoint = current_endpoint()
    if endpoint is None or not endpoint.enabled:
        return None, None, None
    # A forked child keeps the mode and folder (so markers stay seeded) but has no blocks.
    block = endpoint._active_block() if endpoint.pid == os.getpid() else None
    return endpoint.mode, endpoint.responses_dir, block


def read_seed(folder: Path | None) -> str | None:
    """The ``marker_seed`` in the folder's manifest, or None if there isn't one."""
    if folder is None:
        return None
    manifest = folder / MANIFEST_NAME
    try:
        stat = manifest.stat()
    except OSError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _lock:
        cached = _seed_cache.get(manifest)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        with manifest.open("rb") as handle:
            seed = tomllib.load(handle).get("marker_seed")
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ModelEndpointError(f"Cannot read {manifest}: {error}") from None
    if seed is not None and (not isinstance(seed, str) or not seed):
        raise ModelEndpointError(f"{manifest}: marker_seed must be a non-empty string.")
    with _lock:
        _seed_cache[manifest] = (stamp, seed)
    return seed


@contextlib.contextmanager
def _folder_lock(folder: Path) -> Iterator[None]:
    """A lock across processes (record runs under pytest-xdist): an atomic mkdir."""
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / ".wardenbot-seed.lock"
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise ModelEndpointError(
                    f"Timed out waiting for {lock}; remove it if no record run is active."
                ) from None
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.rmdir()


def write_seed(folder: Path) -> str:
    """Give the folder's manifest a random ``marker_seed`` if it has none; return the seed.

    The line goes at the top of the manifest, before any table, so the file
    stays valid TOML and everything else in it is kept byte for byte. Record
    runs in several processes agree on one seed: the check and the write
    happen under a lock, and the file is replaced atomically.
    """
    existing = read_seed(folder)
    if existing is not None:
        return existing
    with _folder_lock(folder):
        with _lock:
            _seed_cache.pop(folder / MANIFEST_NAME, None)
        existing = read_seed(folder)  # another process may have written it meanwhile
        if existing is not None:
            return existing
        seed = secrets.token_urlsafe(18)
        manifest = folder / MANIFEST_NAME
        previous = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
        line = (
            f'marker_seed = "{seed}"  # derives per-case markers; changing it invalidates '
            "hash-matched recordings\n"
        )
        handle, temporary = tempfile.mkstemp(dir=folder, prefix=f".{MANIFEST_NAME}.")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(line + previous)
        os.replace(temporary, manifest)
        with _lock:
            _seed_cache.pop(manifest, None)
    return seed


def _seed(mode: str, folder: Path | None) -> str:
    global _warned_default_seed
    seed = read_seed(folder)
    if seed is not None:
        return seed
    if mode == "replay" and not _warned_default_seed:
        _warned_default_seed = True
        where = folder / MANIFEST_NAME if folder is not None else "the response folder"
        warnings.warn(
            f"No marker_seed in {where}, so injection markers use the fixed default seed. "
            "A record run writes one; recordings made with another seed won't match.",
            UserWarning,
            stacklevel=4,
        )
    return DEFAULT_SEED


def _derive(seed: str, purpose: str, case: str) -> bytes:
    return hmac.new(seed.encode(), f"{purpose}\0{case}".encode(), hashlib.sha256).digest()


def _marker_from(digest: bytes) -> str:
    return MARKER_PREFIX + base64.b32encode(digest).decode().lower()[:16]


def _canary_from(digest: bytes) -> str:
    return CANARY_PREFIX + base64.urlsafe_b64encode(digest).decode().rstrip("=")[:32]


def _value(purpose: str, case: str | None) -> str:
    mode, folder, block = _endpoint_state()
    name = case if case is not None else (block.case if block is not None else current_case())
    if purpose == "canary":
        if block is not None and block.canary and name == block.case:
            return block.canary  # the wardenbot_canary fixture, which reads WARDENBOT_CANARY
        configured = os.environ.get("WARDENBOT_CANARY", "").strip()
        if configured:
            return configured
    shape = _marker_from if purpose == "marker" else _canary_from
    if mode in SEEDED_MODES:
        return shape(_derive(_seed(mode, folder), purpose, name))
    with _lock:
        value = _random.get((purpose, name))
        if value is None:
            if purpose == "marker":
                value = shape(secrets.token_bytes(32))
            else:
                value = generate_canary_token()
            _random[(purpose, name)] = value
    return value


def injection_marker(case: str | None = None) -> str:
    """The injection marker for a case: plant it in untrusted input, then look for it.

    ``case`` defaults to the active ``model_endpoint`` block's case, else the
    running test's id. In ``record``, ``replay`` and ``override`` the marker is
    derived from the case and the response folder's ``marker_seed``, so it is
    the same in every run; otherwise it is random but stable within the
    process. It replaces fixed trigger words such as ``COMPROMISED``, which
    real text can contain.
    """
    return _value("marker", case)


def case_canary(case: str | None = None) -> str:
    """A canary token for a case, shaped like ``generate_canary_token()``.

    A configured canary is used as is: the ``canary=`` of the case's
    ``model_endpoint`` block (the ``wardenbot_model`` fixture passes the
    ``wardenbot_canary`` fixture's value), else ``WARDENBOT_CANARY``. Use a fixed
    one with recordings: a canary that changes between runs changes the
    request hash. Otherwise the canary is derived
    like ``injection_marker``: stable per case in ``record``, ``replay`` and
    ``override``, random but stable within the process in other modes.
    """
    return _value("canary", case)
