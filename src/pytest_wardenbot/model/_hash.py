"""Request hashes: what makes two model requests the same request.

A hash covers the method, the path without its query string, and the whole
JSON body with keys sorted, so it includes ``stream``, tools, Responses
``text.format`` and Chat ``response_format``. Fields listed in
``ignore_fields`` are dropped first, and every string value is normalized:
ISO dates and UUIDs become placeholders, then the configured normalizers run.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

HASH_LENGTH = 16
"""Hex characters of the SHA-256 digest used in file names and miss reports."""

_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_ISO_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
)

Normalizer = Callable[[str], str]


def builtin_normalize(text: str) -> str:
    """Replace UUIDs with ``<uuid>`` and ISO dates and datetimes with ``<date>``."""
    return _ISO_DATE.sub("<date>", _UUID.sub("<uuid>", text))


def _drop(body: dict[str, Any], field: str) -> None:
    *parents, last = field.split(".")
    node: Any = body
    for part in parents:
        node = node.get(part) if isinstance(node, dict) else None
    if isinstance(node, dict):
        node.pop(last, None)


def _normalize(value: Any, normalizers: tuple[Normalizer, ...]) -> Any:
    if isinstance(value, str):
        for normalize in normalizers:
            value = normalize(value)
        return value
    if isinstance(value, dict):
        return {key: _normalize(item, normalizers) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, normalizers) for item in value]
    return value


class RequestHasher:
    """Hashes requests the way a response folder is configured to."""

    def __init__(
        self, ignore_fields: Iterable[str] = (), normalizers: Iterable[Normalizer] = ()
    ) -> None:
        self.ignore_fields = tuple(ignore_fields)
        self.normalizers: tuple[Normalizer, ...] = (builtin_normalize, *normalizers)

    def normalized(self, body: Mapping[str, Any]) -> Any:
        """The body with ignored fields dropped and every string normalized."""
        prepared = copy.deepcopy(dict(body))
        for field in self.ignore_fields:
            _drop(prepared, field)
        return _normalize(prepared, self.normalizers)

    def canonical(
        self, method: str, path: str, body: Mapping[str, Any], *, indent: int | None = None
    ) -> str:
        """The exact text that is hashed (``indent`` only for showing diffs)."""
        document = {
            "method": method.upper(),
            "path": path.split("?", 1)[0],
            "body": self.normalized(body),
        }
        separators = (",", ":") if indent is None else (",", ": ")
        return json.dumps(
            document, sort_keys=True, ensure_ascii=False, separators=separators, indent=indent
        )

    def digest(self, method: str, path: str, body: Mapping[str, Any]) -> str:
        """The request hash: the first 16 hex characters of the canonical text's SHA-256."""
        canonical = self.canonical(method, path, body).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()[:HASH_LENGTH]
