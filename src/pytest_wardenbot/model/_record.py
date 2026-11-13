"""Record mode: write each upstream reply where replay will read it.

- A matching manifest rule: its ``file``, or the Nth of its ``files`` on call N.
  A rule with ``record = false``, or one that points at a ``.jsonl`` file, is
  served from that file with no upstream call.
- A case folder: its files, overwritten in call order.
- Anything else: ``recorded/<case>/<hash>-N.json`` (``.sse`` for streams), with a
  ``<hash>-N.request.json`` sidecar holding the method, path, status and
  request body, which the miss report diffs against.

On a case's first write in a run, ``recorded/<case>/`` is cleared, so no stale
recording can answer in front of a new one; earlier versions stay in git.
Request headers are never written, the path is stored without its query
string, and a non-2xx reply is never saved.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._cases import claim_case_dirname
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._folder import (
    SIDECAR_SUFFIX,
    LookupState,
    ResponseFolder,
    reply_files,
)
from pytest_wardenbot.model._reply import Reply
from pytest_wardenbot.model._upstream import assistant_text, body_from_stream


@dataclass(frozen=True)
class Target:
    """Where one recorded reply goes."""

    path: Path
    kind: str
    sidecar: Path | None = None


class Recorder:
    """Plans and writes recordings for one response folder."""

    def __init__(self, folder: ResponseFolder) -> None:
        self.folder = folder
        self._cleared: set[str] = set()
        self._lock = threading.Lock()

    def plan(
        self, request: CapturedRequest, case: str | None, state: LookupState
    ) -> Reply | Target:
        """A reply to serve locally (``record = false`` and ``.jsonl`` rules), or a target."""
        if case is None:
            raise ModelEndpointError(
                "Record mode can only save requests made inside a model_endpoint block, which "
                f"names the case; this request to {request.path} was outside any block."
            )
        folder = self.folder
        digest = folder.hasher.digest(request.method, request.path, request.body)
        rule = folder.match_rule(request, case, digest, [])
        if rule is not None:
            if not rule.record or rule.jsonl:
                return folder.serve_rule(rule, case, state)
            return Target(folder.rule_target(rule, state), kind=rule.describe())
        dirname = claim_case_dirname(case)
        case_folder = folder.root / "cases" / dirname
        if case_folder.is_dir():
            files = reply_files(case_folder)
            index = state.next_case_call()
            if index < len(files):
                return Target(files[index], kind=f"cases/{dirname}/")
        name = f"{digest}-{state.next_hash_call(digest)}"
        recorded = folder.root / "recorded" / dirname
        return Target(
            recorded / f"{name}{'.sse' if request.stream else '.json'}",
            kind=f"recorded/{dirname}/",
            sidecar=recorded / f"{name}{SIDECAR_SUFFIX}",
        )

    def save(
        self, target: Target, request: CapturedRequest, case: str, raw: bytes, status: int
    ) -> None:
        """Write a successful upstream reply to ``target``, converted to the file's format."""
        content = _convert(raw, request, target.path)
        recorded = self.folder.root / "recorded" / claim_case_dirname(case)
        with self._lock:
            if recorded.name not in self._cleared:
                self._cleared.add(recorded.name)
                if recorded.is_dir():
                    shutil.rmtree(recorded)
            _write(target.path, content)
            if target.sidecar is not None:
                sidecar = {
                    "method": request.method,
                    "path": request.path,
                    "status": status,
                    "request": request.body,
                }
                text = json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n"
                _write(target.sidecar, text.encode("utf-8"))


def _convert(raw: bytes, request: CapturedRequest, path: Path) -> bytes:
    suffix = path.suffix.lower()
    if request.stream:
        if suffix == ".sse":
            return raw
        body = body_from_stream(raw, request.api)
    else:
        if suffix == ".sse":
            raise ModelEndpointError(
                f"{path.name} is an event stream (.sse), but the request didn't stream, so the "
                "reply can't be recorded there. Point the rule at a .json file."
            )
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ModelEndpointError(f"The upstream reply is not JSON: {error}") from None
    if suffix == ".txt":
        return assistant_text(body).encode("utf-8")
    return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _write(path: Path, content: bytes) -> None:
    """Write atomically, so a crash never leaves half a reply behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(content)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
