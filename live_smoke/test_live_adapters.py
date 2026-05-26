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


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
def test_openai_chat_adapter_round_trips() -> None:
    from pytest_wardenbot.adapters.openai_chat import OpenAIChatAdapter

    adapter = OpenAIChatAdapter(model="gpt-4o-mini")
    response = adapter.send_message(_PROMPT)

    assert response.text.strip(), "expected a non-empty reply from the live API"
    assert response.latency_ms is not None and response.latency_ms >= 0


@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set")
def test_anthropic_messages_adapter_round_trips() -> None:
    from pytest_wardenbot.adapters.anthropic_msgs import AnthropicMessagesAdapter

    adapter = AnthropicMessagesAdapter(model="claude-haiku-4-5", max_tokens=64)
    response = adapter.send_message(_PROMPT)

    assert response.text.strip(), "expected a non-empty reply from the live API"
    assert response.latency_ms is not None and response.latency_ms >= 0
