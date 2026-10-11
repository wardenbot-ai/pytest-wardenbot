# Community release and CI updates

The optional **Community updates** workflow can post a short status and a link to
an Actions run in Slack, Discord, or both. It never posts commit messages,
release notes, artifacts, or arbitrary text. No webhook messages are sent until
the repository variable `COMMUNITY_NOTIFICATIONS_ENABLED` is set to `true`.

## Set up Slack

1. Create a Slack app for your workspace, enable **Incoming Webhooks**, and
   choose **Add New Webhook to Workspace**. Select the channel for release
   announcements and copy the generated webhook URL. Follow Slack's
   [incoming webhook setup guide](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/).
2. In the repository's
   [Actions secrets settings](https://github.com/wardenbot-ai/pytest-wardenbot/settings/secrets/actions),
   add `COMMUNITY_SLACK_WEBHOOK_URL` with that URL as its value.

Slack receives a plain-text Block Kit status with a button linking to the
workflow run. The text does not interpret mentions.

## Set up Discord

1. In the target channel's settings, open **Integrations → Webhooks**, create a
   webhook, and copy its URL. See Discord's
   [webhook resource guide](https://docs.discord.com/developers/resources/webhook).
2. In the repository's
   [Actions secrets settings](https://github.com/wardenbot-ai/pytest-wardenbot/settings/secrets/actions),
   add `COMMUNITY_DISCORD_WEBHOOK_URL` with that URL as its value.

Discord receives a fixed status and run link with all mentions disabled.

Store each URL only as its matching GitHub Actions secret. Never paste a
webhook URL into an issue, pull request, chat, or workflow input. Either
provider may be configured on its own; a failure at one provider does not stop
an attempt at the other.

## Enable notifications

In the repository's
[Actions variables settings](https://github.com/wardenbot-ai/pytest-wardenbot/settings/variables/actions),
create the variable `COMMUNITY_NOTIFICATIONS_ENABLED` and set it to `true`.
The workflow can then announce successful tagged runs of **Release**. Failed
runs and manually dispatched Release runs are ignored.

CI posts are separate and stay off by default. To enable them too, set
`COMMUNITY_NOTIFY_CI` to `true`. Only a successful **CI** run from a push to
`main` in this repository is announced. Pull request runs, including runs from
forks, are ignored.

The notification workflow checks out the repository's default branch and reads
the workflow event summary. It does not check out a triggering commit or read
artifacts. The message contains a short fixed status and a link to that run.

## Preview the setup

Open **Actions → Community updates → Run workflow** and leave `dry_run` checked
(it is checked by default). The run prints the fixed Slack and Discord payloads
without contacting either webhook; no secrets are needed for the preview. The
preview uses the current workflow run link and does not send a community
announcement. Uncheck `dry_run` only when notifications are enabled and you
intend to post the fixed setup preview to the configured destinations.
