"""Output graders: what a pipeline did with a reply, checked without a model.

Run them on the application's result after a scripted, replayed or mutated
reply. They walk pydantic models, dataclasses, mappings, lists and strings, so
they work on whatever the pipeline returns.

- ``find_marker`` / ``assert_marker_absent``: did the injection marker reach the
  output?
- ``assert_only_known_ids``: did the pipeline keep an id it never issued?
- ``assert_all_ids_accounted``: did it silently drop an id the model omitted?
- ``assert_unique_ids``: did it keep a duplicate?
- ``assert_links_allowed``: could the rendered output send data to another host?

The injection marker itself comes from ``pytest_wardenbot.model.injection_marker``.
"""

from __future__ import annotations

import dataclasses
import html
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import FunctionType, MethodType, ModuleType
from typing import Any
from urllib.parse import urlsplit

from pytest_wardenbot._formatting import format_check_failure
from pytest_wardenbot.canary import canary_present

__all__ = [
    "Link",
    "assert_all_ids_accounted",
    "assert_links_allowed",
    "assert_marker_absent",
    "assert_only_known_ids",
    "assert_unique_ids",
    "find_links",
    "find_marker",
]

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


_OPAQUE = (type, FunctionType, MethodType, ModuleType, int, float, complex, bool)


def _plain(value: Any) -> Any:
    """Models, dataclasses, attrs classes and plain objects as mappings; the rest unchanged.

    Pydantic v2 (``model_dump``) and v1 (``dict``), dataclasses, attrs classes,
    named tuples, and any other object's public attributes.
    """
    if value is None or isinstance(value, (*_OPAQUE, str, bytes, bytearray, Mapping)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump()
    if hasattr(value, "__fields__") and callable(getattr(value, "dict", None)):
        return value.dict()  # pydantic v1
    if dataclasses.is_dataclass(value):
        return {f.name: getattr(value, f.name) for f in dataclasses.fields(value)}
    if hasattr(value, "__attrs_attrs__"):
        return {a.name: getattr(value, a.name) for a in value.__attrs_attrs__}
    as_dict = getattr(value, "_asdict", None)
    if isinstance(value, tuple) and callable(as_dict):
        return as_dict()  # a named tuple
    if isinstance(value, Enum):
        return value.value
    if not isinstance(value, Sequence | set | frozenset) and hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return value


def _strings(
    value: Any, path: str = "", seen: dict[int, Any] | None = None
) -> Iterator[tuple[str, str]]:
    """Every string in ``value``, keys included, with its path, such as ``ratings[2].reason``."""
    # Holds what it has walked, so a freed temporary's id can't be mistaken for a cycle.
    seen = {} if seen is None else seen
    value = _plain(value)
    if isinstance(value, str):
        yield path, value
        return
    if isinstance(value, bytes | bytearray):
        yield path, bytes(value).decode("utf-8", errors="replace")
        return
    if id(value) in seen:
        return  # a cycle
    if isinstance(value, Mapping):
        seen[id(value)] = value
        for key, item in value.items():
            name = str(key)
            step = (f".{name}" if path else name) if _IDENTIFIER.match(name) else f"[{key!r}]"
            if isinstance(key, str):
                yield f"{path}{step} (the key)", key  # keys can come from model output too
            yield from _strings(item, path + step, seen)
    elif isinstance(value, Sequence | set | frozenset):
        seen[id(value)] = value
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]", seen)


def find_marker(obj: Any, marker: str) -> list[str]:
    """The paths of the strings in ``obj`` that contain ``marker``, such as ``ratings[2].reason``.

    Matching folds case, whitespace, zero-width characters and Markdown
    emphasis, as ``canary_present`` does, so a model that splits or restyles
    the marker is still found. A plain string's path is ``"$"``.
    """
    return [path or "$" for path, text in _strings(obj) if canary_present(text, marker)]


def assert_marker_absent(obj: Any, marker: str) -> None:
    """Fail if the injection marker appears anywhere in ``obj``."""
    paths = find_marker(obj, marker)
    if not paths:
        return
    raise AssertionError(
        format_check_failure(
            kind="injection marker in the output",
            sections=(
                ("Marker", marker),
                ("Found in", "\n".join(paths)),
                (
                    "Why this matters",
                    "The marker was planted in untrusted input. Finding it in the output "
                    "means text the attacker controlled flowed through to the result.",
                ),
            ),
            output=str(_plain(obj)),
            remediation=(
                "Don't copy untrusted text or the model's free text into fields that are shown "
                "or acted on without checking them. Keep only fields the application can "
                "validate (ids it issued, booleans, enums), or escape and label untrusted text "
                "where it is displayed."
            ),
        )
    )


_MISSING = object()


def _id_of(item: Any, key: str | None) -> Any:
    if key is None:
        return item
    if isinstance(item, Mapping):
        return item.get(key)
    value = getattr(item, key, _MISSING)  # an attribute, without dumping the whole item
    if value is not _MISSING:
        return value
    plain = _plain(item)
    return plain.get(key) if isinstance(plain, Mapping) else None


def _ids(items: Iterable[Any], key: str | None) -> list[Any]:
    if isinstance(items, str | bytes) or not isinstance(items, Iterable):
        items = _plain(items)
    if isinstance(items, str | bytes) or not isinstance(items, Iterable):
        raise TypeError(f"Expected a list of items, not {type(items).__name__}.")
    return [_id_of(item, key) for item in items]


def _hashable(value: Any) -> Any:
    """``value`` as a set member: unhashable ids (a list the model returned) by content."""
    try:
        hash(value)
    except TypeError:
        return ("unhashable", json.dumps(value, sort_keys=True, default=repr))
    return value


def _many(values: Any, what: str) -> list[Any]:
    """A collection argument; a lone string is one value, not its characters."""
    if isinstance(values, str | bytes):
        return [values]
    if not isinstance(values, Iterable):
        raise TypeError(f"{what} must be a list, not {type(values).__name__}.")
    return list(values)


def _where(key: str | None) -> str:
    return "the items" if key is None else f"the {key!r} field"


def assert_only_known_ids(items: Iterable[Any], key: str | None, allowed: Iterable[Any]) -> None:
    """Fail on any item whose id the application never issued.

    ``key`` names the id field of each item (a mapping key or attribute); with
    ``key=None`` the items are the ids themselves, as in ``flagged_post_ids``.
    """
    allowed = _many(allowed, "allowed")
    known = {_hashable(value) for value in allowed}
    unknown = [
        (index, value)
        for index, value in enumerate(_ids(items, key))
        if _hashable(value) not in known
    ]
    if not unknown:
        return
    raise AssertionError(
        format_check_failure(
            kind="unknown id in the output",
            sections=(
                ("Ids the application issued", ", ".join(sorted(map(repr, allowed)))),
                (
                    f"Not issued, in {_where(key)}",
                    "\n".join(f"item {index}: {value!r}" for index, value in unknown),
                ),
            ),
            remediation=(
                "Bind the model's output to the ids the application issued: look each id up "
                "in the batch you sent and drop anything else, instead of trusting the ids "
                "the model returns. An injected document can make the model invent ids."
            ),
        )
    )


def assert_all_ids_accounted(
    items: Iterable[Any], key: str | None, expected: Iterable[Any]
) -> None:
    """Fail when an id the application issued is missing from the result.

    Catches pipelines that silently drop what the model omitted, instead of
    marking it as unknown.
    """
    present = {_hashable(value) for value in _ids(items, key)}
    missing = [value for value in _many(expected, "expected") if _hashable(value) not in present]
    if not missing:
        return
    raise AssertionError(
        format_check_failure(
            kind="issued id missing from the output",
            sections=(("Missing ids", ", ".join(map(repr, missing))),),
            remediation=(
                "Return one result for every item the application sent, and mark items the "
                "model skipped explicitly (for example relevant=None) instead of dropping "
                "them. An injected document can make the model omit other items."
            ),
        )
    )


def assert_unique_ids(items: Iterable[Any], key: str | None) -> None:
    """Fail when the same id appears more than once."""
    seen: dict[Any, tuple[Any, list[int]]] = {}
    for index, value in enumerate(_ids(items, key)):
        seen.setdefault(_hashable(value), (value, []))[1].append(index)
    duplicated = {repr(value): indexes for value, indexes in seen.values() if len(indexes) > 1}
    if not duplicated:
        return
    raise AssertionError(
        format_check_failure(
            kind="duplicate id in the output",
            sections=(
                (
                    f"Duplicated in {_where(key)}",
                    "\n".join(f"{value}: items {indexes}" for value, indexes in duplicated.items()),
                ),
            ),
            remediation=(
                "Key results by the ids the application issued, keeping one result per id, "
                "so a model that repeats an item can't count it twice."
            ),
        )
    )


@dataclass(frozen=True)
class Link:
    """A link or image found in output: its URL, its kind and where it was."""

    url: str
    kind: str
    path: str = "$"

    @property
    def is_image(self) -> bool:
        """Fetched when rendered, with no click: images, embeds, stylesheets, refreshes."""
        return self.kind in {"markdown image", "html image or embed"}


# Link text may hold escaped brackets and one level of nested brackets: [see [1] here].
_LINK_TEXT = r"(?:[^\[\]\\]|\\.|\[(?:[^\[\]\\]|\\.)*\])*"
_MARKDOWN_IMAGE = re.compile(r"!\[" + _LINK_TEXT + r"\]\(\s*<?([^)\s>]+)")
_MARKDOWN_LINK = re.compile(r"(?<!!)\[" + _LINK_TEXT + r"\]\(\s*<?([^)\s>]+)")
_IMAGE_REFERENCE = re.compile(r"!\[(" + _LINK_TEXT + r")\](?:\[(" + _LINK_TEXT + r")\])?(?!\()")
# Definitions may sit in block quotes: > [r]: https://...
_REFERENCE = re.compile(
    r"^(?:[ \t]{0,3}>)*[ \t]{0,3}\[(" + _LINK_TEXT + r")\]:[ \t]*<?(\S+?)>?(?:[ \t]+.*)?$",
    re.MULTILINE,
)
_AUTOLINK = re.compile(r"<([A-Za-z][A-Za-z0-9+.-]{1,31}:[^>\s]+)>")
_TAG = re.compile(r"<([A-Za-z][\w:-]*)((?:\s[^>]*)?)/?>")
_ATTRIBUTE = re.compile(r"([\w:.-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))")
_CSS_URL = re.compile(r"url\(\s*[\"']?([^\"')\s]+)", re.IGNORECASE)
_REFRESH_URL = re.compile(r"url\s*=\s*['\"]?([^'\"\s;]+)", re.IGNORECASE)
# Attributes a renderer fetches with no click, and the tags whose href does too.
_FETCHED = frozenset({"src", "data", "poster", "background", "xlink:href", "srcset", "lowsrc"})
_FETCHED_HREF_TAGS = frozenset({"link", "image", "use", "feimage", "script"})
_NAVIGATED = frozenset({"href", "action", "formaction", "ping", "cite", "longdesc"})
_BARE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'()\[\]]+", re.IGNORECASE)
_ALWAYS_BLOCKED_SCHEMES = frozenset({"javascript", "data", "vbscript"})
_WEB_SCHEMES = frozenset({"http", "https", "ftp", "ws", "wss"})


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _html_links(text: str, path: str) -> list[Link]:
    found: list[Link] = []
    for tag in _TAG.finditer(text):
        name = tag.group(1).lower()
        attributes = {
            match.group(1).lower(): next(g for g in match.groups()[1:] if g is not None)
            for match in _ATTRIBUTE.finditer(tag.group(2))
        }
        for attribute, value in attributes.items():
            if attribute == "srcset":
                found += [
                    Link(candidate.strip().split()[0], "html image or embed", path)
                    for candidate in value.split(",")
                    if candidate.strip()
                ]
            elif attribute in _FETCHED or (attribute == "href" and name in _FETCHED_HREF_TAGS):
                found.append(Link(value, "html image or embed", path))
            elif attribute == "ping":
                found += [Link(url, "html link", path) for url in value.split()]
            elif attribute in _NAVIGATED:
                found.append(Link(value, "html link", path))
            elif attribute == "style":
                found += [
                    Link(m.group(1), "html image or embed", path)
                    for m in _CSS_URL.finditer(html.unescape(value))
                ]
        if name == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            match = _REFRESH_URL.search(attributes.get("content", ""))
            if match:  # navigates with no click
                found.append(Link(match.group(1), "html image or embed", path))
    return found


def _links_in(text: str, path: str, bare_urls: bool) -> list[Link]:
    found = [Link(m.group(1), "markdown image", path) for m in _MARKDOWN_IMAGE.finditer(text)]
    found += [Link(m.group(1), "markdown link", path) for m in _MARKDOWN_LINK.finditer(text)]
    image_labels = {_label(m.group(2) or m.group(1)) for m in _IMAGE_REFERENCE.finditer(text)}
    found += [
        Link(
            m.group(2),
            "markdown image" if _label(m.group(1)) in image_labels else "markdown reference",
            path,
        )
        for m in _REFERENCE.finditer(text)
    ]
    found += [Link(m.group(1), "autolink", path) for m in _AUTOLINK.finditer(text)]
    found += _html_links(text, path)
    if bare_urls:
        taken = {link.url for link in found}
        found += [
            Link(m.group(0), "bare url", path)
            for m in _BARE.finditer(text)
            if m.group(0) not in taken
        ]
    return [Link(html.unescape(link.url).strip(), link.kind, link.path) for link in found]


def find_links(obj_or_text: Any, *, bare_urls: bool = False) -> list[Link]:
    """Every Markdown and HTML link and image in a string, or in every string of an object.

    Covers Markdown links, images, reference definitions (reference-style images
    count as images) and autolinks. In HTML: ``href``, ``src``, ``srcset``,
    ``xlink:href``, ``action``, ``formaction``, ``ping``, ``background``, CSS
    ``url()`` in ``style``, and meta refresh. Anything fetched without a click
    (images, embeds, stylesheets, SVG ``image`` and ``use``, a refresh) is an
    image (``Link.is_image``). HTML entities in URLs are decoded; HTML-escaped
    markup (``&lt;img ...&gt;``) is inert and not counted. Bare URLs count only
    with ``bare_urls=True``.
    """
    return [
        link
        for path, text in _strings(obj_or_text)
        for link in _links_in(text, path or "$", bare_urls)
    ]


def _host_allowed(host: str, allowed: Sequence[str]) -> bool:
    for pattern in allowed:
        pattern = pattern.lower().rstrip(".")
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _browser_parts(url: str) -> tuple[str, str]:
    """The scheme and host a browser would use, read the WHATWG way.

    Tabs and newlines are dropped, backslashes count as slashes, and a web
    scheme without slashes (``https:evil.example``) still names a host. Raises
    ValueError for a URL that can't be parsed.
    """
    url = re.sub(r"[\t\n\r]", "", url).strip("\x00 ")
    if url.lower().startswith("www."):
        url = f"https://{url}"
    scheme_match = re.match(r"([A-Za-z][A-Za-z0-9+.-]*):", url)
    scheme = scheme_match.group(1).lower() if scheme_match else ""
    if scheme in _WEB_SCHEMES or not scheme:
        url = url.replace("\\", "/")
    if scheme in _WEB_SCHEMES:
        rest = url[len(scheme) + 1 :].lstrip("/")
        url = f"{scheme}://{rest}"
    parts = urlsplit(url)
    return scheme, (parts.hostname or "").lower().rstrip(".")


def _refusal(link: Link, allowed: Sequence[str], images: bool) -> str | None:
    """Why ``link`` isn't allowed, or None."""
    try:
        scheme, host = _browser_parts(link.url)
    except ValueError:
        return "the URL is malformed, so its host can't be checked"
    if scheme in _ALWAYS_BLOCKED_SCHEMES:
        return f"{scheme}: URLs are never allowed"
    if link.is_image and not images:
        return "images are not allowed (pass images=True to allow them from allowed hosts)"
    if not host:
        if scheme:
            return f"a {scheme}: URL has no host the allowlist can check"
        return None  # a relative link stays on the application's own site
    if not _host_allowed(host, allowed):
        return f"{host} is not an allowed host"
    return None


def assert_links_allowed(
    obj_or_text: Any,
    allowed_hosts: Iterable[str],
    images: bool = False,
    *,
    bare_urls: bool = False,
) -> None:
    """Fail on any link or image that could send data outside ``allowed_hosts`` when rendered.

    Hosts match exactly (case-insensitively), or by wildcard: ``*.example.com``
    allows its subdomains. URLs are read as browsers read them (backslashes
    count as slashes). Relative links are allowed; a URL with a scheme but no
    host (``mailto:``) or that can't be parsed fails. ``javascript:``,
    ``data:`` and ``vbscript:`` URLs always fail. With ``images=False``, any
    image fails, even from an allowed host: a rendered image is fetched with no
    click, which is how a beacon leaks data. ``bare_urls=True`` also checks
    plain URLs, for renderers that turn them into links.
    """
    allowed = [str(host) for host in _many(allowed_hosts, "allowed_hosts")]
    bad = [
        (link, reason)
        for link in find_links(obj_or_text, bare_urls=bare_urls)
        if (reason := _refusal(link, allowed, images)) is not None
    ]
    if not bad:
        return
    raise AssertionError(
        format_check_failure(
            kind="link or image to a host that isn't allowed",
            sections=(
                ("Allowed hosts", ", ".join(allowed) or "(none)"),
                (
                    "Refused",
                    "\n".join(
                        f"{link.kind} at {link.path}: {link.url[:200]!r} ({reason})"
                        for link, reason in bad
                    ),
                ),
                (
                    "Why this matters",
                    "Output the application renders can make the reader's browser request any "
                    "URL in it. An injected document can make the model add a link or image "
                    "that carries private data to the attacker's host.",
                ),
            ),
            output=obj_or_text if isinstance(obj_or_text, str) else str(_plain(obj_or_text)),
            remediation=(
                "Render links only to hosts the application chose (for example the URLs of "
                "the documents it retrieved) and render images as text, or strip them. Do the "
                "check on the rendered HTML, after Markdown is converted."
            ),
        )
    )
