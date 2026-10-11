"""Post fixed, trusted GitHub workflow status updates to community webhooks.

This script deliberately sends only a bounded status label and a GitHub Actions
run link. It never forwards commit messages, release notes, workflow artifacts,
or arbitrary event text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_TIMEOUT_SECONDS = 8
_MAX_RESPONSE_BYTES = 1024
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?$")
_SLACK_PATH_RE = re.compile(r"^/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$")
_DISCORD_PATH_RE = re.compile(r"^/api/webhooks/\d+/[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class Update:
    status: str
    url: str


class SafeNotificationError(Exception):
    """An error whose message contains no webhook credential material."""


class InvalidWebhookURL(SafeNotificationError, ValueError):
    pass


class WebhookDeliveryError(SafeNotificationError, RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def _same_repository(event: dict[str, Any], repository: str) -> bool:
    run = event.get("workflow_run")
    if not isinstance(run, dict):
        return False
    event_repository = event.get("repository")
    head_repository = run.get("head_repository")
    return (
        isinstance(event_repository, dict)
        and event_repository.get("full_name") == repository
        and isinstance(head_repository, dict)
        and head_repository.get("full_name") == repository
    )


def update_from_event(
    event: dict[str, Any],
    *,
    repository: str,
    notify_ci: bool,
) -> Update | None:
    """Return an update only for successful same-repository push workflows."""
    if not _REPOSITORY_RE.fullmatch(repository) or event.get("action") != "completed":
        return None
    if not _same_repository(event, repository):
        return None

    run = event["workflow_run"]
    if run.get("conclusion") != "success":
        return None
    workflow = run.get("name")
    trigger_event = run.get("event")
    branch = run.get("head_branch")
    run_id = run.get("id")
    if not isinstance(run_id, int) or run_id <= 0:
        return None

    if workflow == "CI":
        if not notify_ci or trigger_event != "push" or branch != "main":
            return None
        status = "CI completed successfully on main."
    elif workflow == "Release":
        if (
            trigger_event != "push"
            or not isinstance(branch, str)
            or not _RELEASE_TAG_RE.fullmatch(branch)
        ):
            return None
        status = "A tagged release completed successfully."
    else:
        return None

    owner_repo = urllib.parse.quote(repository, safe="/")
    return Update(status=status, url=f"https://github.com/{owner_repo}/actions/runs/{run_id}")


def _preview_update(repository: str, run_id: str) -> Update:
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("GITHUB_REPOSITORY must have owner/repository form")
    if not run_id.isdigit() or int(run_id) <= 0:
        raise ValueError("GITHUB_RUN_ID must be a positive integer")
    owner_repo = urllib.parse.quote(repository, safe="/")
    return Update(
        status="Community notification preview (no workflow status was sent).",
        url=f"https://github.com/{owner_repo}/actions/runs/{int(run_id)}",
    )


def _webhook_url(value: str, provider: str) -> str:
    """Validate webhook destinations without returning the secret URL in errors."""
    try:
        parsed = urllib.parse.urlsplit(value)
        valid_common = (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.query
            and not parsed.fragment
        )
    except (TypeError, ValueError):
        valid_common = False
        parsed = urllib.parse.urlsplit("")

    if provider == "Slack":
        valid = (
            valid_common
            and parsed.hostname == "hooks.slack.com"
            and bool(_SLACK_PATH_RE.fullmatch(parsed.path))
        )
    else:
        valid = (
            valid_common
            and parsed.hostname in {"discord.com", "discordapp.com"}
            and bool(_DISCORD_PATH_RE.fullmatch(parsed.path))
        )
    if not valid:
        raise InvalidWebhookURL(f"{provider} webhook URL is invalid; check its HTTPS host and path")
    return value


def _payload(update: Update, provider: str) -> dict[str, Any]:
    if provider == "Slack":
        return {
            "text": update.status,
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": update.status, "emoji": False},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View workflow run", "emoji": True},
                        "url": update.url,
                        "action_id": "view_workflow_run",
                    },
                }
            ],
        }
    return {
        "content": f"{update.status}\n{update.url}",
        "allowed_mentions": {"parse": []},
    }


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _post(url: str, payload: dict[str, Any], provider: str) -> None:
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "pytest-wardenbot-community-updates",
        },
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler)
        response = opener.open(request, timeout=_TIMEOUT_SECONDS)
        with response:
            status = getattr(response, "status", 200)
            response.read(_MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        raise WebhookDeliveryError(f"{provider} webhook returned HTTP {exc.code}") from None
    except Exception as exc:
        # Exception strings from urllib can include the full secret webhook URL.
        raise WebhookDeliveryError(
            f"{provider} webhook request failed ({type(exc).__name__})"
        ) from None
    if not 200 <= status < 300:
        raise WebhookDeliveryError(f"{provider} webhook returned HTTP {status}")


def notify(
    update: Update,
    *,
    slack_url: str | None,
    discord_url: str | None,
    dry_run: bool,
    output: Any | None = None,
) -> bool:
    """Send independently to configured providers; return false if any fails."""
    if output is None:
        output = sys.stdout
    assert output is not None
    providers = (("Slack", slack_url), ("Discord", discord_url))
    results: list[tuple[str, str]] = []
    configured = 0
    success = True
    for provider, raw_url in providers:
        payload = _payload(update, provider)
        if not raw_url:
            if dry_run:
                output.write(f"{provider} payload: {json.dumps(payload, sort_keys=True)}\n")
            results.append((provider, "skipped (webhook not configured)"))
            continue
        configured += 1
        try:
            url = _webhook_url(raw_url, provider)
            if dry_run:
                output.write(f"{provider} payload: {json.dumps(payload, sort_keys=True)}\n")
            else:
                _post(url, payload, provider)
            results.append((provider, "dry run" if dry_run else "sent"))
        except SafeNotificationError as exc:
            results.append((provider, f"failed ({exc!s})"))
            success = False
        except Exception as exc:
            # Unexpected exception messages can also contain webhook URLs.
            results.append((provider, f"failed (unexpected {type(exc).__name__})"))
            success = False

    if configured == 0:
        output.write(
            "Community updates skipped: no webhooks configured "
            "(set COMMUNITY_SLACK_WEBHOOK_URL and/or COMMUNITY_DISCORD_WEBHOOK_URL).\n"
        )
    summary = "; ".join(f"{name}: {state}" for name, state in results)
    output.write(f"Community notification status: {summary}\n")
    return success


def _read_event(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"GitHub event file could not be read ({type(exc).__name__})") from None
    if not isinstance(value, dict):
        raise ValueError("GitHub event payload must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-file", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--preview", action="store_true", help="build a fixed setup-preview status")
    parser.add_argument("--dry-run", action="store_true", help="print payloads without sending")
    args = parser.parse_args(argv)

    if args.preview:
        try:
            update = _preview_update(
                os.environ.get("GITHUB_REPOSITORY", ""),
                os.environ.get("GITHUB_RUN_ID", ""),
            )
        except ValueError as exc:
            sys.stderr.write(f"Community notification configuration error: {exc}\n")
            return 2
        if not args.dry_run and not _enabled(os.environ.get("COMMUNITY_NOTIFICATIONS_ENABLED")):
            sys.stdout.write(
                "Community notifications are disabled; set COMMUNITY_NOTIFICATIONS_ENABLED=true.\n"
            )
            return 0
    else:
        if not _enabled(os.environ.get("COMMUNITY_NOTIFICATIONS_ENABLED")):
            sys.stdout.write(
                "Community notifications are disabled; set COMMUNITY_NOTIFICATIONS_ENABLED=true.\n"
            )
            return 0
        if not args.event_file:
            sys.stderr.write(
                "Community notification configuration error: GITHUB_EVENT_PATH is missing.\n"
            )
            return 2
        try:
            event = _read_event(args.event_file)
        except ValueError as exc:
            sys.stderr.write(f"Community notification input error: {exc}\n")
            return 2
        repository = os.environ.get("GITHUB_REPOSITORY", "")
        update = update_from_event(
            event,
            repository=repository,
            notify_ci=_enabled(os.environ.get("COMMUNITY_NOTIFY_CI")),
        )
        if update is None:
            sys.stdout.write(
                "Community notification skipped: event did not match an enabled successful "
                "CI or tagged release.\n"
            )
            return 0

    sent = notify(
        update,
        slack_url=os.environ.get("COMMUNITY_SLACK_WEBHOOK_URL"),
        discord_url=os.environ.get("COMMUNITY_DISCORD_WEBHOOK_URL"),
        dry_run=args.dry_run,
    )
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
