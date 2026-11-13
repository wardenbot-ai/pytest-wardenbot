"""The one model call the example pipelines share: OpenAI Chat Completions in JSON mode."""

from __future__ import annotations

import json
from typing import Any

import openai  # type: ignore[import-not-found]

MODEL = "gpt-4.1-mini"
_client: openai.OpenAI | None = None


def client() -> openai.OpenAI:
    """A client built once and cached, as applications usually do.

    It reads OPENAI_BASE_URL and OPENAI_API_KEY, which the model endpoint set
    before the tests imported this module.
    """
    global _client
    if _client is None:
        _client = openai.OpenAI(max_retries=0)
    return _client


def ask_model(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Make one Chat Completions call with response_format json_object; return the JSON."""
    reply = client().chat.completions.create(
        model=MODEL, messages=messages, response_format={"type": "json_object"}
    )
    return json.loads(reply.choices[0].message.content or "{}")
