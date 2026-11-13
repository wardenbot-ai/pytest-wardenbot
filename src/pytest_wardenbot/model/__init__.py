"""Deterministic tests for LLM pipelines: a local OpenAI-compatible model endpoint.

The endpoint lets an application's own SDK client run against scripted,
replayed or recorded replies, so prompt assembly and output handling can be
tested in CI without an API key. Nothing in this package imports pytest: it
works the same under pytest, ``unittest`` and Django's ``manage.py test``.

    from pytest_wardenbot.model import install, model_endpoint

    install()  # before the application is imported

    with model_endpoint(script={"ratings": []}) as ep:
        rate_sources(sources)
    assert ep.requests[0].text("user")
"""

from __future__ import annotations

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._endpoint import (
    Endpoint,
    EndpointCase,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._guard import EgressBlockedError
from pytest_wardenbot.model._markers import MARKER_PREFIX, case_canary, injection_marker
from pytest_wardenbot.model._reply import Reply, ToolCall, WebSearch
from pytest_wardenbot.model._script import Script

__all__ = [
    "MARKER_PREFIX",
    "CapturedRequest",
    "EgressBlockedError",
    "Endpoint",
    "EndpointCase",
    "ModelEndpointError",
    "Reply",
    "Script",
    "ToolCall",
    "WebSearch",
    "case_canary",
    "injection_marker",
    "install",
    "model_endpoint",
    "uninstall",
]
