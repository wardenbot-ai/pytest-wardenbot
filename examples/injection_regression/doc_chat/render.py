"""Turn the assistant's Markdown into the HTML the chat UI shows. Deliberately small."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


def _paragraphs(text: str) -> str:
    return "".join(f"<p>{part}</p>" for part in text.split("\n\n") if part.strip())


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
    text = _IMAGE.sub(lambda m: f"[image: {m[1]}]", text)

    def link(match: re.Match[str]) -> str:
        host = urlsplit(html.unescape(match[2])).hostname or ""
        return f'<a href="{match[2]}">{match[1]}</a>' if host in allowed else match[1]

    return _paragraphs(_LINK.sub(link, text))
