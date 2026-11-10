# Security Policy

## Reporting

Email `security@wardenbot.ai`. Do not file public GitHub issues for security
reports.

We aim to acknowledge within 24 hours and provide an initial assessment within
5 business days.

## Supported versions

Beta. The latest 0.x minor release (currently 0.5.x) is the supported line.
Security fixes ship as patches on that line. See the
[versioning and stability policy](docs/reference/stability.md).

## Scope

In scope:

- The installed `pytest-wardenbot` package on PyPI
- The GitHub repository at `wardenbot-ai/pytest-wardenbot`
- Generated `conftest.py` / `test_my_bot.py` templates

Out of scope (report to [WardenBot AI](https://wardenbot.ai/.well-known/security.txt) instead):

- The managed monitoring service at `wardenbot.ai`
- Marketing site, dashboard, or any hosted infrastructure

## Disclosure

We follow coordinated disclosure. Once a fix is released, we will credit
reporters in the release notes unless they prefer to remain anonymous.
