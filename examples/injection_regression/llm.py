"""The model calls the example pipelines share.

Chat Completions in JSON mode for patterns A and B, and a streaming Responses
call for pattern C. One cached client reads OPENAI_BASE_URL and
OPENAI_API_KEY, which the model endpoint set before the tests imported this.
"""

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


def stream_answer(instructions: str, input: str | list[dict[str, str]]) -> str:  # noqa: A002
    """Make one streaming Responses call; return the text the deltas spell out.

    A stream that fails or stops early raises, rather than passing off part of
    an answer as the whole.
    """
    stream = client().responses.create(
        model=MODEL, instructions=instructions, input=input, stream=True
    )
    parts: list[str] = []
    for event in stream:
        if event.type == "response.output_text.delta":
            parts.append(event.delta)
        elif event.type in {"error", "response.failed", "response.incomplete"}:
            raise RuntimeError(f"The model's stream ended with {event.type}.")
    return "".join(parts)
