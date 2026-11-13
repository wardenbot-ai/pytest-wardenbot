"""The response-folder manifest: ``wardenbot-responses.toml``.

It holds the ``marker_seed``, ``allow_patterns`` for the credential scan, and
``[[response]]`` rules. Rules are checked in file order and the first match
wins. Every match field a rule sets must match:

- ``case``: the full case name, or its last component (after the last ``::``,
  or for ids without one, after the last ``.``);
- ``path`` and ``model``: the request's path and model, exactly;
- ``contains`` and ``regex``: the request's prompt text (every role's text);
- ``request_hash``: the request hash shown in a miss report.

A rule serves ``file``, or ``files`` in order with ``then`` deciding what
follows the last one. A ``file`` ending in ``.jsonl`` picks one entry with
``line = N`` or ``where = {field = value}``, whatever the request hash.
"""

from __future__ import annotations

import re
import threading
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._errors import ModelEndpointError

MANIFEST_NAME = "wardenbot-responses.toml"
MATCH_FIELDS = ("case", "path", "model", "contains", "regex", "request_hash")
SERVE_FIELDS = ("file", "files", "then", "record", "line", "where")
TOP_LEVEL = ("marker_seed", "allow_patterns", "response")
THEN = ("fail", "repeat_last")


def last_component(case: str) -> str:
    """The part of a case name a rule's ``case`` may name on its own.

    After the last ``::`` for pytest node ids, so parametrize ids such as
    ``test_x[1.5]`` stay whole; after the last ``.`` for unittest ids.
    """
    if "::" in case:
        return case.rsplit("::", 1)[1]
    return case.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Rule:
    """One ``[[response]]`` rule."""

    index: int
    match: Mapping[str, str]
    file: str | None = None
    files: tuple[str, ...] = ()
    then: str = "fail"
    record: bool = True
    line: int | None = None
    where: Mapping[str, Any] | None = None
    pattern: re.Pattern[str] | None = field(default=None, compare=False)

    @property
    def targets(self) -> tuple[str, ...]:
        """The files this rule serves, in order."""
        return (self.file,) if self.file is not None else self.files

    @property
    def jsonl(self) -> bool:
        return self.file is not None and self.file.lower().endswith(".jsonl")

    def describe(self) -> str:
        fields = ", ".join(f"{key} = {value!r}" for key, value in self.match.items())
        return f"rule {self.index}" + (f" ({fields})" if fields else " (matches everything)")

    def mismatch(self, request: CapturedRequest, case: str | None, digest: str) -> str | None:
        """None when the rule matches; otherwise why it doesn't."""
        for key, expected in self.match.items():
            if key == "case":
                if case is None:
                    return "case: the request was made outside any model_endpoint block"
                if expected not in (case, last_component(case)):
                    return f"case: {expected!r} is not {case!r} or {last_component(case)!r}"
            elif key == "path" and expected != request.path:
                return f"path: {expected!r} is not {request.path!r}"
            elif key == "model" and expected != request.model:
                return f"model: {expected!r} is not {request.model!r}"
            elif key == "contains" and expected not in request.text():
                return f"contains: {expected!r} is not in the prompt text"
            elif key == "regex":
                assert self.pattern is not None
                if self.pattern.search(request.text()) is None:
                    return f"regex: {expected!r} doesn't match the prompt text"
            elif key == "request_hash" and expected != digest:
                return f"request_hash: {expected!r} is not {digest!r}"
        return None


@dataclass(frozen=True)
class Manifest:
    """A parsed ``wardenbot-responses.toml``."""

    path: Path
    marker_seed: str | None = None
    allow_patterns: tuple[str, ...] = ()
    rules: tuple[Rule, ...] = ()


def _error(path: Path, where: str, message: str) -> ModelEndpointError:
    return ModelEndpointError(f"{path}, {where}: {message}")


def _parse_rule(path: Path, index: int, table: Any) -> Rule:
    where = f"[[response]] rule {index}"
    if not isinstance(table, Mapping):
        raise _error(path, where, "must be a table.")
    unknown = sorted(set(table) - set(MATCH_FIELDS) - set(SERVE_FIELDS))
    if unknown:
        raise _error(
            path,
            where,
            f"unknown key(s) {', '.join(map(repr, unknown))}. Match on "
            f"{', '.join(MATCH_FIELDS)}; serve with {', '.join(SERVE_FIELDS)}.",
        )
    match: dict[str, str] = {}
    for key in MATCH_FIELDS:
        if key in table:
            if not isinstance(table[key], str) or not table[key]:
                raise _error(path, where, f"`{key}` must be a non-empty string.")
            match[key] = table[key]
    pattern = None
    if "regex" in match:
        try:
            pattern = re.compile(match["regex"])
        except re.error as error:
            message = f"`regex` is not a valid regular expression: {error}"
            raise _error(path, where, message) from None
    if ("file" in table) == ("files" in table):
        raise _error(path, where, "set exactly one of `file` or `files`.")
    file = table.get("file")
    files: tuple[str, ...] = ()
    if file is not None and (not isinstance(file, str) or not file):
        raise _error(path, where, "`file` must be a non-empty string.")
    if "files" in table:
        value = table["files"]
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise _error(path, where, "`files` must be a non-empty list of strings.")
        if any(item.lower().endswith(".jsonl") for item in value):
            raise _error(
                path, where, "`files` can't name a .jsonl file; use `file` with `line` or `where`."
            )
        files = tuple(value)
    then = table.get("then", "fail")
    if "then" in table and "files" not in table:
        raise _error(path, where, "`then` only applies to `files`.")
    if then not in THEN:
        raise _error(path, where, f"`then` must be one of {', '.join(THEN)}.")
    record = table.get("record", True)
    if not isinstance(record, bool):
        raise _error(path, where, "`record` must be true or false.")
    line = table.get("line")
    selector = table.get("where")
    is_jsonl = isinstance(file, str) and file.lower().endswith(".jsonl")
    if (line is not None or selector is not None) and not is_jsonl:
        raise _error(path, where, "`line` and `where` only apply to a .jsonl `file`.")
    if is_jsonl:
        if (line is None) == (selector is None):
            raise _error(path, where, "a .jsonl `file` needs exactly one of `line` or `where`.")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
            raise _error(path, where, "`line` must be a whole number from 1.")
        if selector is not None and (not isinstance(selector, Mapping) or not selector):
            raise _error(path, where, "`where` must be a non-empty table.")
    for target in (file, *files):
        if isinstance(target, str) and (Path(target).is_absolute() or ".." in Path(target).parts):
            raise _error(path, where, f"{target!r} must be a path inside the response folder.")
    return Rule(
        index=index,
        match=match,
        file=file,
        files=files,
        then=then,
        record=record,
        line=line,
        where=dict(selector) if selector is not None else None,
        pattern=pattern,
    )


def parse_manifest(path: Path) -> Manifest:
    """Read and validate a manifest, naming the file and rule in every error."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except OSError as error:
        raise ModelEndpointError(f"Cannot read {path}: {error}") from None
    except tomllib.TOMLDecodeError as error:
        raise ModelEndpointError(f"{path} is not valid TOML: {error}") from None
    unknown = sorted(set(data) - set(TOP_LEVEL))
    if unknown:
        raise ModelEndpointError(
            f"{path}: unknown key(s) {', '.join(map(repr, unknown))}. A manifest holds "
            f"{', '.join(TOP_LEVEL)} ([[response]] rules)."
        )
    seed = data.get("marker_seed")
    if seed is not None and (not isinstance(seed, str) or not seed):
        raise ModelEndpointError(f"{path}: marker_seed must be a non-empty string.")
    patterns = data.get("allow_patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
        raise ModelEndpointError(f"{path}: allow_patterns must be a list of strings.")
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as error:
            raise ModelEndpointError(f"{path}: allow_patterns {pattern!r}: {error}") from None
    rules = data.get("response", [])
    if not isinstance(rules, list):
        raise ModelEndpointError(f"{path}: `response` must be [[response]] tables.")
    return Manifest(
        path=path,
        marker_seed=seed,
        allow_patterns=tuple(patterns),
        rules=tuple(_parse_rule(path, index, table) for index, table in enumerate(rules, 1)),
    )


_cache: dict[Path, tuple[float, Manifest]] = {}
_cache_lock = threading.Lock()


def load_manifest(folder: Path) -> Manifest | None:
    """The folder's manifest, re-read when it changes; None if there isn't one."""
    path = folder / MANIFEST_NAME
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    with _cache_lock:
        cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    manifest = parse_manifest(path)
    with _cache_lock:
        _cache[path] = (mtime, manifest)
    return manifest


def shadowed_rules(manifest: Manifest) -> list[tuple[Rule, Rule]]:
    """``(rule, earlier)`` pairs where ``earlier`` matches every request ``rule`` would.

    Conservative: an earlier rule shadows a later one only when its match
    fields are a subset of the later rule's, with the same values, so a rule
    that can still match is never reported.
    """
    found: list[tuple[Rule, Rule]] = []
    for position, rule in enumerate(manifest.rules):
        for earlier in manifest.rules[:position]:
            if earlier.match.items() <= rule.match.items():
                found.append((rule, earlier))
                break
    return found
