"""Record mode: write each upstream reply where replay will read it.

Each request goes through the same steps replay takes, so replay finds every
reply in the order it was recorded:

- A matching manifest rule: its ``file``, or the Nth of its ``files`` on call N.
  A rule with ``record = false``, or one that points at a ``.jsonl`` file, is
  served from that file with no upstream call.
- A ``.jsonl`` entry with the request's hash: served, with no upstream call,
  since replay would answer from it before anything recorded.
- A case folder: its files, overwritten in call order; further calls add files
  that sort after the last one.
- Anything else: ``recorded/<case>/<hash>-N.json`` (``.sse`` for streams), with a
  ``<hash>-N.request.json`` sidecar holding the method, path, status and
  request body, which the miss report diffs against.

On a case's first write, files in ``recorded/<case>/`` from before the run are
deleted, so no stale recording can answer in front of a new one (earlier
versions stay in git). Files other processes of the same run wrote, such as
other pytest-xdist workers, are kept: the run's start time is shared through
``WARDENBOT_RECORD_STARTED_NS``. Request headers are never written, the path is
stored without its query string, and a non-2xx reply is never saved.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._cases import claim_case_dirname
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._folder import (
    SIDECAR_SUFFIX,
    LookupState,
    ResponseFolder,
    natural_key,
    reply_files,
)
from pytest_wardenbot.model._markers import folder_lock
from pytest_wardenbot.model._reply import Reply
from pytest_wardenbot.model._scan import refuse, scan_file, scan_text
from pytest_wardenbot.model._upstream import assistant_text, body_from_stream

STARTED_ENV = "WARDENBOT_RECORD_STARTED_NS"


def run_started_ns() -> int:
    """When this record run started, shared with child processes and xdist workers."""
    value = os.environ.get(STARTED_ENV, "")
    if value.isdigit():
        return int(value)
    started = time.time_ns()
    os.environ[STARTED_ENV] = str(started)
    return started


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
        self.started_ns = run_started_ns()
        self._cleared: set[str] = set()
        self._lock = threading.Lock()

    def plan(
        self, request: CapturedRequest, case: str | None, state: LookupState, *, saving: bool = True
    ) -> Reply | Target | None:
        """A reply to serve locally (``record = false`` and ``.jsonl``), or a target.

        With ``saving=False`` (a mutated case, never recorded) there is no
        target: None means the upstream answers.
        """
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
            if not saving:
                return None
            return _checked(Target(folder.rule_target(rule, state), kind=rule.describe()), request)
        # The steps replay takes, in its order (recorded/ is about to be rewritten).
        call = state.next_hash_call(digest)
        logged = folder.find_jsonl(digest, call, case, [], folder.jsonl_entries())
        if logged is not None:
            return logged
        if not saving:
            return None
        dirname = claim_case_dirname(case)
        extension = ".sse" if request.stream else ".json"
        case_folder = folder.root / "cases" / dirname
        if case_folder.is_dir():
            files = reply_files(case_folder)
            index = state.next_case_call()
            if index < len(files):
                return _checked(Target(files[index], kind=f"cases/{dirname}/"), request)
            added = _next_file(case_folder, files, index, extension)
            return Target(added, kind=f"cases/{dirname}/")
        name = f"{digest}-{call}"
        recorded = folder.root / "recorded" / dirname
        return Target(
            recorded / f"{name}{extension}",
            kind=f"recorded/{dirname}/",
            sidecar=recorded / f"{name}{SIDECAR_SUFFIX}",
        )

    def save(
        self, target: Target, request: CapturedRequest, case: str, raw: bytes, status: int
    ) -> None:
        """Write a successful upstream reply to ``target``, converted to the file's format.

        The reply and its sidecar are scanned for credentials first; a match is
        refused and nothing is written.
        """
        content = _convert(raw, request, target.path)
        sidecar_text = None
        if target.sidecar is not None:
            sidecar = {
                "method": request.method,
                "path": request.path,
                "status": status,
                "request": request.body,
            }
            sidecar_text = json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n"
        allow = self.folder.allow_patterns()
        name = self.folder.relative(target.path)
        findings = scan_file(content.decode("utf-8", errors="replace"), name, allow)
        if sidecar_text is not None and target.sidecar is not None:
            findings += scan_text(sidecar_text, self.folder.relative(target.sidecar), allow)
        refuse(findings, action=f"record {name}")
        recorded = self.folder.root / "recorded" / claim_case_dirname(case)
        with self._lock:
            if recorded.name not in self._cleared:
                self._clear_stale(recorded)
                self._cleared.add(recorded.name)
            _write(target.path, content)
            if target.sidecar is not None and sidecar_text is not None:
                _write(target.sidecar, sidecar_text.encode("utf-8"))

    def _clear_stale(self, recorded: Path) -> None:
        """Delete what an earlier run left in ``recorded/<case>/``, never this run's files."""
        if not recorded.is_dir():
            return
        with folder_lock(self.folder.root):  # other workers may be writing here
            for path in recorded.iterdir():
                try:
                    if path.is_file() and path.stat().st_mtime_ns < self.started_ns:
                        path.unlink()
                except FileNotFoundError:
                    pass


def _checked(target: Target, request: CapturedRequest) -> Target:
    """Refuse a target that can't hold the reply before the upstream is paid for it."""
    if target.path.suffix.lower() == ".sse" and not request.stream:
        raise ModelEndpointError(
            f"{target.path.name} is an event stream (.sse), but the request didn't stream, so "
            "the reply can't be recorded there. Point the rule at a .json file."
        )
    return target


def _next_file(folder: Path, files: list[Path], index: int, extension: str) -> Path:
    """A new case-folder file that sorts after every existing one."""
    last = files[-1] if files else None
    if last is None:
        return folder / f"{index + 1}{extension}"
    key = natural_key(last)
    number = key[1] + 1 if len(key) > 1 and key[0] == "" else index + 1
    candidate = folder / f"{number}{extension}"
    if natural_key(candidate) > key and not candidate.exists():
        return candidate
    return folder / f"{last.stem}~{index + 1}{extension}"  # "~" sorts after "."


def _convert(raw: bytes, request: CapturedRequest, path: Path) -> bytes:
    suffix = path.suffix.lower()
    if request.stream:
        if suffix == ".sse":
            return raw
        body = body_from_stream(raw, request.api)
    else:
        try:
            body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ModelEndpointError(f"The upstream reply is not JSON: {error}") from None
        if not isinstance(body, dict):
            raise ModelEndpointError("The upstream reply is not a JSON object.")
    if suffix == ".txt":
        _refuse_non_text(body, path)
        # End with the newline editors and hooks add; the loader drops exactly one.
        return (assistant_text(body) + "\n").encode("utf-8")
    return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _refuse_non_text(body: Mapping[str, Any], path: Path) -> None:
    """A .txt file holds text only: refuse to drop tool calls or refusals silently."""
    found: set[str] = set()
    if body.get("object") == "response":
        for item in body.get("output") or ():
            if not isinstance(item, Mapping):
                continue
            kind = str(item.get("type"))
            if kind == "message":
                found.update(
                    "refusal"
                    for part in item.get("content") or ()
                    if isinstance(part, Mapping) and part.get("type") == "refusal"
                )
            elif kind != "reasoning":
                found.add(kind)
    else:
        for choice in body.get("choices") or ():
            message = choice.get("message") if isinstance(choice, Mapping) else None
            if isinstance(message, Mapping):
                found.update(key for key in ("tool_calls", "refusal") if message.get(key))
    if found:
        raise ModelEndpointError(
            f"The reply holds {', '.join(sorted(found))}, which {path.name} can't: a .txt file "
            "holds text only. Record into a .json file instead."
        )


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
