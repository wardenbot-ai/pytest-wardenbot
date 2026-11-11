"""The README's chatbot quickstart works as written, and its numbers are true.

The agent quickstart runs end to end in ``test_quickstart_agent.py``. Here the
chatbot path runs literally against a local bot that counts requests, and
every ``--wardenbot-*`` option the docs mention must exist.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from pytest_wardenbot.quickstart import generate

ROOT = Path(__file__).resolve().parents[1]
pytest_plugins = ["pytester"]


class CountingBot:
    """A scoped bot that declines everything and counts the requests it gets."""

    reply = "Sorry, I can only help with questions about your Acme Shoes orders."

    def __init__(self) -> None:
        self.requests = 0
        bot = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                bot.requests += 1
                self.rfile.read(int(self.headers.get("content-length", 0)))
                body = json.dumps({"response": bot.reply}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/chat"

    def __enter__(self) -> CountingBot:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_readme_chatbot_quickstart_runs_and_its_numbers_hold(pytester, monkeypatch):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    claim = re.search(r"pytest\s+# (\d+) checks, about (\d+) requests to your bot", readme)
    assert claim, "README chatbot quickstart lost its check and request counts"
    checks, requests = int(claim[1]), int(claim[2])

    generate("generic", pytester.path)
    with CountingBot() as bot:
        monkeypatch.setenv("CHATBOT_URL", bot.url)
        monkeypatch.delenv("CHATBOT_TOKEN", raising=False)
        monkeypatch.delenv("WARDENBOT_CANARY", raising=False)
        result = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-q")
    # The placeholder business facts are skipped until they are replaced.
    result.assert_outcomes(passed=checks, skipped=2)
    assert bot.requests == requests
    for page in ("docs/index.md", "docs/how-to/ci-integration.md", "docs/quickstart.md"):
        assert str(requests) in (ROOT / page).read_text(encoding="utf-8"), page


def _registered_options() -> set[str]:
    sources = [
        ROOT / "src/pytest_wardenbot/plugin.py",
        ROOT / "src/pytest_wardenbot/_agent_plugin.py",
    ]
    options: set[str] = set()
    for source in sources:
        options |= set(re.findall(r'"(--wardenbot-[a-z-]+)"', source.read_text(encoding="utf-8")))
    return options


def test_documented_options_exist():
    registered = _registered_options()
    assert "--wardenbot-quickstart" in registered
    pages = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    pages += sorted((ROOT / "examples").rglob("*.md"))
    unknown = {
        f"{page.relative_to(ROOT)}: {option}"
        for page in pages
        for option in re.findall(r"--wardenbot-[a-z-]*[a-z]", page.read_text(encoding="utf-8"))
        if option not in registered
    }
    assert not unknown, sorted(unknown)


@pytest.mark.parametrize("template", ["generic", "agent"])
def test_quickstart_templates_named_in_the_docs_exist(template):
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    flag = "--wardenbot-quickstart" + ("" if template == "generic" else f"={template}")
    assert flag in readme


def test_snippet_includes_are_intact():
    """MkDocs includes must keep their exact syntax and point at real files."""
    pages = sorted((ROOT / "docs").rglob("*.md"))
    includes = [
        (page, line)
        for page in pages
        for line in page.read_text(encoding="utf-8").splitlines()
        if "--8" in line
    ]
    assert includes, "the docs include example files with --8<--"
    for page, line in includes:
        match = re.fullmatch(r'--8<-- "([^"]+)"', line.strip())
        assert match, f"{page.relative_to(ROOT)}: malformed include {line!r}"
        assert (ROOT / match[1]).is_file(), f"{page.relative_to(ROOT)}: missing {match[1]}"
