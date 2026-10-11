"""Check a deployed docs site, including its navigation, assets, and repo links."""

from __future__ import annotations

import argparse
import subprocess
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urldefrag, urljoin, urlsplit

REPOSITORY = "https://github.com/wardenbot-ai/pytest-wardenbot"


class Document(HTMLParser):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.links: set[str] = set()
        self.assets: set[str] = set()
        self.ids: set[str] = set()
        self.has_heading = False
        self.feed(content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if identifier := values.get("id"):
            self.ids.add(identifier)
        if tag == "h1":
            self.has_heading = True
        if tag == "a" and (href := values.get("href")):
            self.links.add(href)
        if tag in {"script", "img"} and (src := values.get("src")):
            self.assets.add(src)
        if tag == "link" and values.get("rel") == "stylesheet" and (href := values.get("href")):
            self.assets.add(href)


def fetch(url: str) -> bytes:
    # curl is available on developer machines and GitHub runners. Fail on HTTP
    # errors; follow canonical-slash redirects just as a browser would.
    return subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location", "--max-time", "30", url],
        check=True,
        capture_output=True,
    ).stdout


def check_site(base_url: str) -> None:
    base_url = base_url.rstrip("/") + "/"
    base = urlsplit(base_url)
    documents: dict[str, Document] = {}
    pending = {base_url}
    assets = {urljoin(base_url, "search/search_index.json")}
    fragments: set[tuple[str, str]] = set()

    def is_internal(url: str) -> bool:
        parsed = urlsplit(url)
        return parsed.netloc == base.netloc and parsed.scheme == base.scheme

    while pending:
        url = pending.pop()
        if url in documents:
            continue
        if not urlsplit(url).path.startswith(base.path):
            raise ValueError(f"Navigation escapes the docs base path: {url}")
        document = Document(fetch(url).decode("utf-8"))
        if not document.has_heading:
            raise ValueError(f"Missing page heading (possible error page): {url}")
        if not any(link.rstrip("/") == REPOSITORY for link in document.links):
            raise ValueError(f"Missing current repository link: {url}")
        documents[url] = document
        for href in document.links:
            target, fragment = urldefrag(urljoin(url, href))
            parsed = urlsplit(target)
            if (
                parsed.netloc == "github.com"
                and "/pytest-wardenbot" in parsed.path
                and not (target == REPOSITORY or target.startswith(REPOSITORY + "/"))
            ):
                raise ValueError(f"Outdated repository link on {url}: {href}")
            if not is_internal(target):
                continue
            if fragment:
                fragments.add((target, unquote(fragment)))
            if target not in documents:
                pending.add(target)
        assets.update(target for src in document.assets if is_internal(target := urljoin(url, src)))

    for url, fragment in fragments:
        if fragment not in documents[url].ids:
            raise ValueError(f"Missing anchor: {url}#{fragment}")
    if urljoin(base_url, "quickstart/") not in documents:
        raise ValueError("Quickstart is missing from navigation")
    for url in sorted(assets):
        content = fetch(url)
        if not content or b"<!doctype html" in content[:100].lower():
            raise ValueError(f"Missing asset (or HTML fallback): {url}")
    print(f"Verified {len(documents)} pages and {len(assets)} assets at {base_url}")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--attempts", type=int, default=1)
    args = parser.parse_args()
    for attempt in range(max(1, args.attempts)):
        try:
            check_site(args.base_url)
            return
        except (ValueError, subprocess.CalledProcessError):
            if attempt + 1 >= args.attempts:
                raise
            time.sleep(15)  # Allow the new deployment to propagate.


if __name__ == "__main__":
    main()
