"""Live-API smoke test for the bundled vendor adapters.

Run by the `live-api-smoke` workflow only (manual dispatch + weekly cron); not
part of the default suite (it lives outside `testpaths`). This verifies the
**adapters** round-trip against the real OpenAI / Anthropic APIs — i.e. that the
request/response shape still matches the vendor SDKs (drift detection). It does
NOT assert anything about a bot's security posture; that's what the shipped
probes are for, and a small model failing a probe is not an adapter failure.
"""

from __future__ import annotations

import os

import pytest

_PROMPT = "Reply with a short, friendly greeting."
_REQUEST_TIMEOUT_SECONDS = 20.0
_MAX_RETRIES = 1


def _require_api_key(name: str) -> None:
    if not os.environ.get(name, "").strip():
        pytest.fail(f"{name} is required for this live smoke test", pytrace=False)


def test_openai_chat_adapter_round_trips() -> None:
    _require_api_key("OPENAI_API_KEY")
    import openai  # type: ignore[import-not-found]

    from pytest_wardenbot.adapters.openai_chat import OpenAIChatAdapter

    with openai.OpenAI(timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES) as client:
        adapter = OpenAIChatAdapter(
            model="gpt-4o-mini",
            client=client,
            extra_request_fields={"max_tokens": 32},
        )
        response = adapter.send_message(_PROMPT)

    assert response.text.strip(), "expected a non-empty reply from the live API"
    assert response.latency_ms is not None and response.latency_ms >= 0


def test_openai_responses_adapter_round_trips() -> None:
    _require_api_key("OPENAI_API_KEY")
    import openai  # type: ignore[import-not-found]

    from pytest_wardenbot.adapters.openai_responses import OpenAIResponsesAdapter

    with openai.OpenAI(timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES) as client:
        adapter = OpenAIResponsesAdapter(
            model="gpt-4o-mini",
            client=client,
            extra_request_fields={"max_output_tokens": 32},
        )
        response = adapter.send_message(_PROMPT)

    assert response.text.strip(), "expected a non-empty reply from the live API"
    assert response.latency_ms is not None and response.latency_ms >= 0


def test_anthropic_messages_adapter_round_trips() -> None:
    _require_api_key("ANTHROPIC_API_KEY")
    import anthropic  # type: ignore[import-not-found]

    from pytest_wardenbot.adapters.anthropic_msgs import AnthropicMessagesAdapter

    with anthropic.Anthropic(timeout=_REQUEST_TIMEOUT_SECONDS, max_retries=_MAX_RETRIES) as client:
        adapter = AnthropicMessagesAdapter(model="claude-haiku-4-5", max_tokens=32, client=client)
        response = adapter.send_message(_PROMPT)

    assert response.text.strip(), "expected a non-empty reply from the live API"
    assert response.latency_ms is not None and response.latency_ms >= 0
