"""Tests for response-payload redaction."""

from __future__ import annotations

from pytest_wardenbot._redaction import (
    REDACTED_PLACEHOLDER,
    redact_response_payload,
)


def test_redacts_top_level_authorization_key() -> None:
    payload = {"response": "ok", "Authorization": "Bearer secret"}
    out = redact_response_payload(payload)
    assert out["Authorization"] == REDACTED_PLACEHOLDER
    assert out["response"] == "ok"


def test_redacts_case_insensitively() -> None:
    payload = {"AUTHORIZATION": "v", "Cookie": "c", "X-Api-Key": "k"}
    out = redact_response_payload(payload)
    assert out["AUTHORIZATION"] == REDACTED_PLACEHOLDER
    assert out["Cookie"] == REDACTED_PLACEHOLDER
    assert out["X-Api-Key"] == REDACTED_PLACEHOLDER


def test_redacts_nested_dict_values() -> None:
    payload = {"outer": {"inner": {"api_key": "sk-abc"}}}
    out = redact_response_payload(payload)
    assert out["outer"]["inner"]["api_key"] == REDACTED_PLACEHOLDER


def test_redacts_keys_inside_list_items() -> None:
    payload = {"items": [{"authorization": "v1"}, {"name": "alice"}]}
    out = redact_response_payload(payload)
    assert out["items"][0]["authorization"] == REDACTED_PLACEHOLDER
    assert out["items"][1]["name"] == "alice"


def test_preserves_unrelated_keys_unchanged() -> None:
    payload = {"name": "alice", "score": 0.95, "nested": {"role": "user"}}
    out = redact_response_payload(payload)
    assert out == payload


def test_returns_input_unchanged_when_not_dict_or_list() -> None:
    assert redact_response_payload("just a string") == "just a string"
    assert redact_response_payload(42) == 42
    assert redact_response_payload(None) is None


def test_redacts_partial_substring_matches() -> None:
    """Keys that *contain* a sensitive part match — e.g. 'X-Auth-Token-Whatever'."""
    payload = {"X-Auth-Token-Whatever": "v"}
    out = redact_response_payload(payload)
    assert out["X-Auth-Token-Whatever"] == REDACTED_PLACEHOLDER


def test_custom_sensitive_parts_override_default() -> None:
    payload = {"authorization": "v", "passport": "p"}
    out = redact_response_payload(payload, sensitive_parts=("passport",))
    # Default sensitive list ignored — only 'passport' redacted.
    assert out["authorization"] == "v"
    assert out["passport"] == REDACTED_PLACEHOLDER


def test_tuple_input_becomes_list_in_output() -> None:
    payload = {"items": ({"api_key": "v"},)}
    out = redact_response_payload(payload)
    assert isinstance(out["items"], list)
    assert out["items"][0]["api_key"] == REDACTED_PLACEHOLDER
