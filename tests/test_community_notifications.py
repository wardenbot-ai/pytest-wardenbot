"""Tests for fixed-status community webhook notifications."""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from typing import Any

import pytest
from scripts import notify_community as community

_REPOSITORY = "wardenbot-ai/pytest-wardenbot"
_SLACK_URL = "https://hooks.slack.com/services/T00000000/B00000000/secret-slack"
_DISCORD_URL = "https://discord.com/api/webhooks/123456789012345678/secret-discord"


def _event(
    *,
    workflow: str = "CI",
    event_name: str = "push",
    branch: str = "main",
    conclusion: str = "success",
    repository: str = _REPOSITORY,
    head_repository: str = _REPOSITORY,
    run_id: int = 123456,
) -> dict[str, Any]:
    return {
        "action": "completed",
        "repository": {"full_name": repository},
        "workflow_run": {
            "id": run_id,
            "name": workflow,
            "event": event_name,
            "head_branch": branch,
            "conclusion": conclusion,
            "head_repository": {"full_name": head_repository},
        },
    }


def test_successful_ci_and_release_events_create_fixed_updates() -> None:
    ci = community.update_from_event(_event(), repository=_REPOSITORY, notify_ci=True)
    release = community.update_from_event(
        _event(workflow="Release", branch="v1.2.3"),
        repository=_REPOSITORY,
        notify_ci=False,
    )

    assert ci == community.Update(
        "CI completed successfully on main.",
        "https://github.com/wardenbot-ai/pytest-wardenbot/actions/runs/123456",
    )
    assert release is not None
    assert release.status == "A tagged release completed successfully."
    assert "v1.2.3" not in release.status


@pytest.mark.parametrize(
    "event,notify_ci",
    [
        (_event(conclusion="failure"), True),
        (_event(event_name="pull_request"), True),
        (_event(branch="feature"), True),
        (_event(), False),
        (_event(head_repository="fork/pytest-wardenbot"), True),
        (_event(repository="fork/pytest-wardenbot"), True),
        (_event(workflow="Other"), True),
        (_event(workflow="Release", event_name="workflow_dispatch", branch="v1.2.3"), True),
        (_event(workflow="Release", branch="main"), True),
        (_event(workflow="Release", branch="v1.2.3", conclusion="failure"), True),
        (_event(run_id=0), True),
    ],
)
def test_untrusted_or_unrequested_events_are_ignored(
    event: dict[str, Any], notify_ci: bool
) -> None:
    assert community.update_from_event(event, repository=_REPOSITORY, notify_ci=notify_ci) is None


def test_payloads_use_plain_text_and_disable_discord_mentions() -> None:
    update = community.Update(
        "CI completed successfully on main.",
        "https://github.com/wardenbot-ai/pytest-wardenbot/actions/runs/123456",
    )

    slack = community._payload(update, "Slack")
    discord = community._payload(update, "Discord")

    assert slack["blocks"][0]["text"]["type"] == "plain_text"
    assert slack["blocks"][0]["accessory"]["url"] == update.url
    assert slack["text"] == update.status
    assert discord["allowed_mentions"] == {"parse": []}
    assert discord["content"] == f"{update.status}\n{update.url}"


def test_dry_run_prints_payloads_without_webhook_urls() -> None:
    output = io.StringIO()
    update = community.Update(
        "Release completed.", "https://github.com/example/repo/actions/runs/4"
    )

    assert community.notify(
        update,
        slack_url=_SLACK_URL,
        discord_url=_DISCORD_URL,
        dry_run=True,
        output=output,
    )

    text = output.getvalue()
    assert "Slack payload:" in text and "Discord payload:" in text
    assert update.url in text
    assert "secret-slack" not in text and "secret-discord" not in text


def test_missing_webhooks_are_reported_as_explicit_skips() -> None:
    output = io.StringIO()
    assert community.notify(
        community.Update("Preview", "https://github.com/example/repo/actions/runs/4"),
        slack_url=None,
        discord_url=None,
        dry_run=False,
        output=output,
    )
    assert "no webhooks configured" in output.getvalue()
    assert "Slack: skipped (webhook not configured)" in output.getvalue()
    assert "Discord: skipped (webhook not configured)" in output.getvalue()


def test_webhook_urls_require_provider_hosts_and_paths() -> None:
    assert community._webhook_url(_SLACK_URL, "Slack") == _SLACK_URL
    assert community._webhook_url(_DISCORD_URL, "Discord") == _DISCORD_URL
    for provider, url in (
        ("Slack", "https://example.com/services/T/B/token"),
        ("Slack", "http://hooks.slack.com/services/T/B/token"),
        ("Discord", "https://discord.com/api/webhooks/1/token?redirect=https://evil.invalid"),
        ("Discord", "https://discord.com.evil.invalid/api/webhooks/1/token"),
    ):
        with pytest.raises(ValueError, match="URL is invalid") as exc_info:
            community._webhook_url(url, provider)
        assert "token" not in str(exc_info.value)


def test_http_mock_sends_each_provider_independently_and_suppresses_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any], float]] = []

    class Response:
        status = 204

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b"secret response body"

    class Opener:
        def open(self, request: Any, timeout: float) -> Response:
            calls.append((request.full_url, json.loads(request.data), timeout))
            if "discord.com" in request.full_url:
                raise urllib.error.HTTPError(
                    request.full_url,
                    429,
                    "secret rate response",
                    hdrs=Message(),
                    fp=None,
                )
            return Response()

    monkeypatch.setattr(community.urllib.request, "build_opener", lambda *_args: Opener())
    output = io.StringIO()
    update = community.Update(
        "CI completed successfully on main.", "https://github.com/example/repo/actions/runs/4"
    )

    assert not community.notify(
        update,
        slack_url=_SLACK_URL,
        discord_url=_DISCORD_URL,
        dry_run=False,
        output=output,
    )

    text = output.getvalue()
    assert len(calls) == 2
    assert calls[0][0] == _SLACK_URL and calls[1][0] == _DISCORD_URL
    assert calls[0][1]["blocks"][0]["text"]["type"] == "plain_text"
    assert all(timeout == community._TIMEOUT_SECONDS for _, _, timeout in calls)
    assert "Slack: sent" in text and "Discord: failed (Discord webhook returned HTTP 429)" in text
    assert "secret" not in text


def test_network_exception_does_not_leak_webhook_url_or_exception_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Opener:
        def open(self, *_args: object, **_kwargs: object) -> None:
            raise OSError(f"cannot connect to {_SLACK_URL}")

    monkeypatch.setattr(community.urllib.request, "build_opener", lambda *_args: Opener())
    output = io.StringIO()

    assert not community.notify(
        community.Update("Preview", "https://github.com/example/repo/actions/runs/4"),
        slack_url=_SLACK_URL,
        discord_url=None,
        dry_run=False,
        output=output,
    )
    assert "Slack webhook request failed (OSError)" in output.getvalue()
    assert "secret-slack" not in output.getvalue()


def test_unexpected_delivery_exception_text_is_not_printed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        community,
        "_post",
        lambda *_args: (_ for _ in ()).throw(RuntimeError(f"leaked {_SLACK_URL}")),
    )
    output = io.StringIO()

    assert not community.notify(
        community.Update("Preview", "https://github.com/example/repo/actions/runs/4"),
        slack_url=_SLACK_URL,
        discord_url=None,
        dry_run=False,
        output=output,
    )
    assert "failed (unexpected RuntimeError)" in output.getvalue()
    assert "secret-slack" not in output.getvalue()


def test_preview_does_not_need_provider_credentials(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPOSITORY)
    monkeypatch.setenv("GITHUB_RUN_ID", "123456")
    monkeypatch.delenv("COMMUNITY_SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("COMMUNITY_DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("COMMUNITY_NOTIFICATIONS_ENABLED", raising=False)
    assert community.main(["--preview", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "Community notification preview" in output
    assert "no webhooks configured" in output
    assert "Slack payload:" in output and "Discord payload:" in output
