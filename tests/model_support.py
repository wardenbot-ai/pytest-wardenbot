"""Shared helpers for the model endpoint tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from pytest_wardenbot.model import Endpoint, install, uninstall
from pytest_wardenbot.model._config import _CI_MARKERS

ENDPOINT_VARIABLES = (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "WARDENBOT_ENDPOINT",
    "WARDENBOT_ORIGINAL_OPENAI_BASE_URL",
    "WARDENBOT_ORIGINAL_OPENAI_API_KEY",
    "WARDENBOT_MODEL_MODE",
    "WARDENBOT_RESPONSES_DIR",
    "WARDENBOT_CONFIG",
    "WARDENBOT_UPSTREAM_BASE_URL",
    "WARDENBOT_RECORD_STARTED_NS",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def clean_environment(monkeypatch: pytest.MonkeyPatch, *, ci: bool = False) -> None:
    """Remove every variable the endpoint reads or writes; optionally leave CI detection."""
    for name in ENDPOINT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    if not ci:
        for name in ("CI", *_CI_MARKERS):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def scripted_endpoint(monkeypatch: pytest.MonkeyPatch) -> Iterator[Endpoint]:
    """An endpoint installed in scripted mode for one test, then removed."""
    clean_environment(monkeypatch)
    uninstall()
    endpoint = install(mode="scripted")
    try:
        yield endpoint
    finally:
        uninstall()


def post(endpoint: Endpoint, path: str, body: dict[str, Any]) -> httpx.Response:
    assert endpoint.url is not None
    return httpx.post(endpoint.url.removesuffix("/v1") + path, json=body, timeout=10)


def sse_events(data: bytes) -> list[tuple[str | None, Any]]:
    """Parse a server-sent event stream into (event, data) pairs."""
    events: list[tuple[str | None, Any]] = []
    for block in data.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        name = None
        payload = ""
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload += line[len("data: ") :]
        events.append((name, payload if payload == "[DONE]" else json.loads(payload)))
    return events


def allow_upstream(monkeypatch: pytest.MonkeyPatch, url: str = "http://127.0.0.1:9/v1") -> None:
    """Give upstream modes a dummy key and a local URL; no test calls a real provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")  # pragma: allowlist secret
    monkeypatch.setenv("WARDENBOT_UPSTREAM_BASE_URL", url)
