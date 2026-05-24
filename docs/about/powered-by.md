# Powered by WardenBot AI

`pytest-wardenbot` is the open-source slice of [WardenBot AI](https://wardenbot.ai)'s
test corpus. WardenBot AI is the company; this plugin is one of two
product lines.

## The two product lines

### Security Audits (one-shot)

One-time, deep, professional audits of an AI application:

- **Tier 1 — Free Surface Recon.** Free reconnaissance scan.
- **Tier 2 — Deep DAST Audit ($1,500).** Full dynamic security testing of
  a web app + AI-aware probes.
- **Tier 3 — AI + Infra Audit ($5,000).** Full AI red-team engagement +
  infrastructure security review.

### Continuous Monitoring (subscription)

Recurring external monitoring of customer-facing chatbots:

- **Watch ($29/mo).** 1 endpoint, daily heartbeat + weekly probe, monthly
  PDF report.
- **Patrol ($79/mo).** 3 endpoints, daily probes, behavior-diff alerts,
  Slack/email.
- **Sentry ($299/mo).** Up to 10 endpoints, hourly probes + adversarial
  agent loop, CI/CD integration, quarterly compliance evidence pack.
- **Castle (custom).** Custom corpus, agency mode, SOC 2 / HIPAA evidence
  packs, dedicated success engineer.

## How this plugin relates

The plugin is **the free, open-source slice of the Continuous Monitoring
test corpus**. 30 curated tests (plus an opt-in canary-leak test, plus
your business-truth and judge lists) that you run locally in your own
pytest suite.

The managed Continuous Monitoring service runs roughly 1000+ tests on a
schedule with cross-run history, alerts on regression, a dashboard, and
the "Bot Health Score" composite.

A typical customer journey:

1. **Find us via the plugin.** Developer runs `pip install pytest-wardenbot`
   in their pre-launch testing.
2. **Upgrade to managed continuous monitoring** when the bot ships and
   they want always-on coverage.
3. **Buy a one-shot Security Audit** at major milestones (pre-launch
   hardening, enterprise sales push, compliance review).

## Why the OSS plugin exists

Two reasons:

1. **Developers can verify the test corpus before paying.** You can read
   every prompt we send and every check we run. No black-box claims.

2. **The plugin is genuinely useful even if you never use the managed
   service.** A solo developer running pytest in CI gets real value
   from the deterministic suite without any subscription.

## How the OSS plugin and the managed service stay in sync

- The plugin's test corpus is a curated subset of the managed-service
  corpus.
- New tests added to the plugin first prove themselves there, then promote
  into the managed-service corpus if they're broadly useful.
- New managed-service tests stay there if they require infrastructure
  the plugin doesn't have (cross-run history, scheduled runs, etc.).

## Want the managed service?

[Tell us about your setup](https://wardenbot.ai/intake/). We open invites
in small batches.
