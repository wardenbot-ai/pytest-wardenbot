"""Turn the assistant's Markdown into the HTML the chat UI shows. Deliberately small."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _paragraphs(text: str) -> str:
    text = text.replace("\r\n", "\n")
    return "".join(f"<p>{part}</p>" for part in re.split(r"\n\s*\n", text) if part.strip())


def _on_site(url: str, allowed: set[str]) -> bool:
    """An http(s) URL to an allowed host, with nothing a browser reads differently.

    Backslashes (browsers treat them as slashes), userinfo (``a@b``) and
    control characters are refused outright rather than parsed.
    """
    if any(char in url for char in "\\@") or any(ord(char) < 0x20 for char in url):
        return False
    parts = urlsplit(url)
    return parts.scheme in {"http", "https"} and (parts.hostname or "") in allowed


def render_everything(markdown: str) -> str:
    """Render every link and image, wherever it points."""
    text = html.escape(markdown)
    text = _IMAGE.sub(lambda m: f'<img src="{m[2]}" alt="{m[1]}">', text)
    text = _LINK.sub(lambda m: f'<a href="{m[2]}">{m[1]}</a>', text)
    return _paragraphs(text)


def render_safely(markdown: str, allowed_hosts: Iterable[str]) -> str:
    """Render images as text, and links only to allowed hosts; other links keep their text."""
    allowed = set(allowed_hosts)
    text = html.escape(markdown)
    # Entity brackets, so the link pass below can't turn "[image: x](url)" into a link.
    text = _IMAGE.sub(lambda m: f"&#91;image: {m[1]}&#93;", text)

    def link(match: re.Match[str]) -> str:
        on_site = _on_site(html.unescape(match[2]), allowed)
        return f'<a href="{match[2]}">{match[1]}</a>' if on_site else match[1]

    return _paragraphs(_LINK.sub(link, text))
