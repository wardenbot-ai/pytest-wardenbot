"""Response folders: reply files the endpoint serves in place of a real model.

A request finds its reply in this order:

1. manifest rules in ``wardenbot-responses.toml``;
2. the request hash, scoped to the case: ``recorded/<case>/<hash>-N.json`` (or
   ``.sse``) and ``.jsonl`` entries whose ``case`` is this case; then ``.jsonl``
   entries with no ``case``;
3. the case folder, ``cases/<case>/``, one file per call in filename order.

A request that matches nothing fails with a report of what was tried.
"""

from __future__ import annotations

import difflib
import json
import re
import shlex
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._cases import claim_case_dirname, pytest_running
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._hash import RequestHasher
from pytest_wardenbot.model._manifest import Manifest, Rule, load_manifest
from pytest_wardenbot.model._markers import fill_placeholders
from pytest_wardenbot.model._reply import Reply

REPLY_SUFFIXES = frozenset({".json", ".txt", ".sse"})
SIDECAR_SUFFIX = ".request.json"
_BODY_OBJECTS = frozenset({"response", "chat.completion"})
_EXCERPT = 200


class ReplayMissError(ModelEndpointError):
    """No reply in the response folder matches a request, in ``replay`` mode.

    The message shows the request, every place that was tried and why it
    didn't match, a diff against the closest recorded request for the case,
    and the command that records the reply.
    """


@dataclass
class LookupState:
    """Per-block call counters, so each block starts at the first reply again.

    Requests in one block can arrive at the same time (an async application),
    so counters are claimed under ``lock``.
    """

    hash_calls: Counter[str] = field(default_factory=Counter)
    case_calls: int = 0
    rule_calls: Counter[int] = field(default_factory=Counter)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def next_hash_call(self, digest: str) -> int:
        with self.lock:
            self.hash_calls[digest] += 1
            return self.hash_calls[digest]

    def next_case_call(self) -> int:
        """The zero-based index of this call into the case folder."""
        with self.lock:
            index = self.case_calls
            self.case_calls += 1
            return index

    def next_rule_call(self, rule: int) -> int:
        with self.lock:
            self.rule_calls[rule] += 1
            return self.rule_calls[rule]


@dataclass(frozen=True)
class JsonlEntry:
    """One line of a ``.jsonl`` file: an exported request and the reply to serve."""

    file: Path
    line: int
    method: str
    path: str
    request: Mapping[str, Any]
    response: Any
    case: str | None
    digest: str
    fields: Mapping[str, Any] = field(default_factory=dict)
    """The line's other top-level fields, which a rule's ``where`` can select on."""

    @property
    def where(self) -> str:
        return f"{self.file.name}:{self.line}"


_DIGITS = re.compile(r"(\d+)")


def natural_key(path: Path) -> list[Any]:
    """Sort ``2.json`` before ``10.json``: numbers in names compare as numbers."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGITS.split(path.name)]


def reply_files(folder: Path) -> list[Path]:
    """A case folder's reply files, in natural filename order."""
    return sorted((path for path in folder.iterdir() if _is_reply_file(path)), key=natural_key)


def _is_reply_file(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in REPLY_SUFFIXES
        and not path.name.endswith(SIDECAR_SUFFIX)
        and not path.name.startswith(".")
    )


def _infer_path(request: Mapping[str, Any]) -> str | None:
    if "messages" in request:
        return "/v1/chat/completions"
    if "input" in request:
        return "/v1/responses"
    return None


def reply_from_value(value: Any, source: str) -> Reply:
    """A reply from a parsed value: a complete body, text, or structured output."""
    if isinstance(value, str):
        return Reply(text=value, source=source)
    if isinstance(value, Mapping) and value.get("object") in _BODY_OBJECTS:
        return Reply(body=dict(value), source=source)
    if value is None:
        raise ModelEndpointError(f"{source} has no reply (it is null).")
    return Reply(text=json.dumps(value, ensure_ascii=False), source=source)


class ResponseFolder:
    """A response folder on disk, read lazily and cached by modification time."""

    def __init__(self, root: Path, hasher: RequestHasher) -> None:
        self.root = root
        self.hasher = hasher
        self._lock = threading.Lock()
        self._jsonl: tuple[tuple[tuple[Path, float], ...], tuple[JsonlEntry, ...]] | None = None

    # Loading --------------------------------------------------------------

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return str(path)

    def load_reply(self, path: Path, case: str | None) -> Reply:
        """Read a reply file; fill placeholders in ``.txt`` and ``.json`` files.

        Response folders get committed, and editors and whitespace hooks (such as
        pre-commit's end-of-file-fixer) end files with exactly one newline. So a
        ``.txt`` reply drops one trailing newline, and an ``.sse`` stream gets its
        final blank line back, without which a client drops the last event.
        """
        return load_reply_file(path, case, self.relative(path))

    def jsonl_entries(self) -> tuple[JsonlEntry, ...]:
        """Every ``.jsonl`` entry in the folder, re-read when a file changes."""
        files = (
            sorted(path for path in self.root.rglob("*.jsonl") if path.is_file())
            if self.root.exists()
            else []
        )
        stamp = tuple((path, path.stat().st_mtime) for path in files)
        with self._lock:
            if self._jsonl is not None and self._jsonl[0] == stamp:
                return self._jsonl[1]
        entries = tuple(entry for path in files for entry in self._read_jsonl(path))
        with self._lock:
            self._jsonl = (stamp, entries)
        return entries

    def _read_jsonl(self, path: Path) -> list[JsonlEntry]:
        entries: list[JsonlEntry] = []
        source = self.relative(path)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ModelEndpointError(f"Cannot read {source}: {error}") from None
        for number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ModelEndpointError(f"{source}:{number} is not valid JSON: {error}") from None
            if not isinstance(record, Mapping) or not isinstance(record.get("request"), Mapping):
                raise ModelEndpointError(
                    f'{source}:{number} must be an object with a "request" object and a "response".'
                )
            if "response" not in record:
                raise ModelEndpointError(f'{source}:{number} has no "response".')
            request = record["request"]
            route = record.get("path") or _infer_path(request)
            if not isinstance(route, str):
                raise ModelEndpointError(
                    f'{source}:{number}: add a "path" (such as "/v1/responses"); it can\'t be '
                    "inferred from the request."
                )
            method = str(record.get("method") or "POST")
            case = record.get("case")
            # Any "headers" key is ignored: logs can carry credentials.
            entries.append(
                JsonlEntry(
                    file=path,
                    line=number,
                    method=method,
                    path=route,
                    request=request,
                    response=record["response"],
                    case=case if isinstance(case, str) else None,
                    digest=self.hasher.digest(method, route, request),
                    fields={
                        key: value
                        for key, value in record.items()
                        if key not in {"request", "response", "headers"}
                    },
                )
            )
        return entries

    # Rules ----------------------------------------------------------------

    def manifest(self) -> Manifest | None:
        return load_manifest(self.root)

    def match_rule(
        self, request: CapturedRequest, case: str | None, digest: str, tried: list[str]
    ) -> Rule | None:
        """The first rule that matches, noting why each earlier one didn't."""
        manifest = self.manifest()
        if manifest is None:
            return None
        for rule in manifest.rules:
            reason = rule.mismatch(request, case, digest)
            if reason is None:
                return rule
            tried.append(f"{rule.describe()}: {reason}")
        return None

    def rule_target(self, rule: Rule, state: LookupState) -> Path:
        """The file a rule serves on this call, advancing its per-block counter."""
        targets = rule.targets
        call = state.next_rule_call(rule.index)
        if call > len(targets):
            if rule.then != "repeat_last":
                raise ModelEndpointError(
                    f"{rule.describe()} in {self.relative(self.root / 'wardenbot-responses.toml')}"
                    f" served all {len(targets)} of its files, and this was call {call}. Add a "
                    'file, or set then = "repeat_last".'
                )
            call = len(targets)
        return self.root / targets[call - 1]

    def jsonl_entry(self, rule: Rule) -> JsonlEntry:
        """The entry a ``.jsonl`` rule picks with ``line`` or ``where``."""
        assert rule.file is not None
        path = self.root / rule.file
        if not path.is_file():
            raise ModelEndpointError(f"{rule.describe()} names {rule.file}, which doesn't exist.")
        entries = [entry for entry in self.jsonl_entries() if entry.file == path]
        if rule.line is not None:
            chosen = [entry for entry in entries if entry.line == rule.line]
            wanted = f"line {rule.line}"
        else:
            assert rule.where is not None
            chosen = [
                entry
                for entry in entries
                if all(
                    (entry.case if key == "case" else entry.fields.get(key)) == value
                    for key, value in rule.where.items()
                )
            ]
            wanted = "where " + ", ".join(f"{k} = {v!r}" for k, v in rule.where.items())
        if not chosen:
            raise ModelEndpointError(f"{rule.describe()}: {rule.file} has no entry with {wanted}.")
        return chosen[0]

    def serve_rule(self, rule: Rule, case: str | None, state: LookupState) -> Reply:
        if rule.jsonl:
            entry = self.jsonl_entry(rule)
            return reply_from_value(entry.response, entry.where)
        path = self.rule_target(rule, state)
        if not path.is_file():
            raise ModelEndpointError(
                f"{rule.describe()} names {self.relative(path)}, which doesn't exist."
            )
        return self.load_reply(path, case)

    # Lookup ---------------------------------------------------------------

    def find(
        self,
        request: CapturedRequest,
        case: str | None,
        state: LookupState,
        *,
        test_id: str | None = None,
    ) -> Reply:
        """The reply for ``request``, or raise ``ReplayMissError`` explaining the miss."""
        tried: list[str] = []
        digest = self.hasher.digest(request.method, request.path, request.body)
        rule = self.match_rule(request, case, digest, tried)
        if rule is not None:
            return self.serve_rule(rule, case, state)
        call = state.next_hash_call(digest)
        entries = self.jsonl_entries()  # walk the folder once per request

        found = self._find_hashed(digest, call, case, tried, entries)
        if found is not None:
            return found
        if case is not None:
            found = self._find_case_folder(case, state, tried)
            if found is not None:
                return found
        report = self.miss_report(request, case, digest, tried, test_id, entries)
        raise ReplayMissError(report)

    def _find_hashed(
        self,
        digest: str,
        call: int,
        case: str | None,
        tried: list[str],
        entries: tuple[JsonlEntry, ...],
    ) -> Reply | None:
        if case is not None:
            folder = self.root / "recorded" / claim_case_dirname(case)
            files = sorted(
                (path for path in folder.glob(f"{digest}-*") if _is_reply_file(path)),
                key=lambda path: _call_number(path.stem),
            )
            if files:
                chosen = next((p for p in files if _call_number(p.stem) == call), files[-1])
                return self.load_reply(chosen, case)
            tried.append(f"recorded/{folder.name}/{digest}-{call}.json (or .sse): not found")
            scoped = [e for e in entries if e.case == case and e.digest == digest]
            if scoped:
                entry = scoped[min(call, len(scoped)) - 1]
                return reply_from_value(entry.response, entry.where)
            tried.append(f".jsonl entries for this case: none with hash {digest}")
        unscoped = [e for e in entries if e.case is None and e.digest == digest]
        if unscoped:
            entry = unscoped[min(call, len(unscoped)) - 1]
            return reply_from_value(entry.response, entry.where)
        tried.append(f".jsonl entries without a case: none with hash {digest}")
        return None

    def _find_case_folder(self, case: str, state: LookupState, tried: list[str]) -> Reply | None:
        folder = self.root / "cases" / claim_case_dirname(case)
        if not folder.is_dir():
            tried.append(f"cases/{folder.name}/: doesn't exist")
            return None
        files = reply_files(folder)
        index = state.next_case_call()
        if index < len(files):
            return self.load_reply(files[index], case)
        tried.append(
            f"cases/{folder.name}/: has {len(files)} file{'s' if len(files) != 1 else ''}, and "
            f"this was call {index + 1}. Add a file, or use a manifest rule with "
            'then = "repeat_last".'
        )
        return None

    # Miss reports ---------------------------------------------------------

    def _closest(
        self, request: CapturedRequest, case: str | None, entries: tuple[JsonlEntry, ...]
    ) -> tuple[str, str] | None:
        if case is None:
            return None
        current = self.hasher.canonical(request.method, request.path, request.body, indent=2)
        candidates: list[tuple[str, str]] = []
        folder = self.root / "recorded" / claim_case_dirname(case)
        for sidecar in sorted(folder.glob(f"*{SIDECAR_SUFFIX}")):
            try:
                recorded = json.loads(sidecar.read_text(encoding="utf-8"))
                text = self.hasher.canonical(
                    str(recorded.get("method", "POST")),
                    str(recorded["path"]),
                    recorded["request"],
                    indent=2,
                )
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
            candidates.append((f"recorded/{folder.name}/{sidecar.name}", text))
        for entry in entries:
            if entry.case == case:
                text = self.hasher.canonical(entry.method, entry.path, entry.request, indent=2)
                candidates.append((entry.where, text))
        if not candidates:
            return None
        where, text = max(
            candidates, key=lambda item: difflib.SequenceMatcher(None, item[1], current).ratio()
        )
        diff = difflib.unified_diff(
            text.splitlines(), current.splitlines(), "recorded", "this request", lineterm="", n=2
        )
        lines = list(diff)
        if len(lines) > 60:
            lines = [*lines[:60], f"... ({len(lines) - 60} more diff lines)"]
        return where, "\n".join(lines)

    def miss_report(
        self,
        request: CapturedRequest,
        case: str | None,
        digest: str,
        tried: Sequence[str],
        test_id: str | None,
        entries: tuple[JsonlEntry, ...] = (),
    ) -> str:
        who = f"case {case!r}" if case is not None else "a request outside any model_endpoint block"
        lines = [
            f"No reply in the response folder {self.root} for {who} (replay mode).",
            "",
            f"Request: {request.method} {request.path}, model {request.model or '(none)'}, "
            f"hash {digest}",
        ]
        for role, text in request.roles:
            excerpt = text if len(text) <= _EXCERPT else text[:_EXCERPT] + "..."
            lines.append(f"  {role}: {excerpt!r}")
        lines += ["", "Tried:"]
        lines += [f"  - {line}" for line in tried]
        closest = self._closest(request, case, entries)
        if closest is not None:
            where, diff = closest
            lines += ["", f"Closest recorded request for this case ({where}):", diff]
        lines += ["", f"To record it, call the real API once: {record_command(test_id)}"]
        return "\n".join(lines)


def load_reply_file(path: Path, case: str | None, source: str) -> Reply:
    """Read a reply file: ``.sse`` raw, ``.txt`` text, ``.json`` a body or structured output.

    Placeholders are filled in text and JSON (JSON-escaped there), a ``.txt``
    reply drops one trailing newline, and an ``.sse`` stream gets its final
    blank line back. Response folders and ``Script.file`` both read this way.
    """
    suffix = path.suffix.lower()
    try:
        if suffix == ".sse":
            return Reply(sse=terminate_stream(path.read_bytes()), source=source)
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ModelEndpointError(f"Cannot read the reply file {source}: {error}") from None
    if suffix == ".txt":
        return Reply(text=_drop_final_newline(fill_placeholders(text, case, source)), source=source)
    if suffix != ".json":
        raise ModelEndpointError(f"{source}: reply files are .json, .txt or .sse.")
    text = fill_placeholders(text, case, source, json_escape=True)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise ModelEndpointError(f"{source} is not valid JSON: {error}") from None
    return reply_from_value(value, source)


def terminate_stream(raw: bytes) -> bytes:
    """Make sure an event stream ends with the blank line that dispatches its last event."""
    if not raw.strip() or raw.endswith((b"\n\n", b"\r\n\r\n")):
        return raw
    return raw + (b"\n" if raw.endswith(b"\n") else b"\n\n")


def _drop_final_newline(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]
    return text[:-1] if text.endswith("\n") else text


def _call_number(stem: str) -> int:
    _, _, number = stem.rpartition("-")
    return int(number) if number.isdigit() else 0


def record_command(test_id: str | None) -> str:
    """The command that re-runs the test in record mode."""
    if test_id is None:
        return (
            "set WARDENBOT_MODEL_MODE=record and OPENAI_API_KEY, then run the test that makes "
            "this request"
        )
    if pytest_running():
        return f"WARDENBOT_MODEL_MODE=record OPENAI_API_KEY=... pytest {shlex.quote(test_id)}"
    return (
        f"WARDENBOT_MODEL_MODE=record OPENAI_API_KEY=... python manage.py test {test_id} "
        "(or your unittest command with that test id)"
    )
