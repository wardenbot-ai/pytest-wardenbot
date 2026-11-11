# Security Policy

## Reporting a vulnerability

Please don't open a public issue, discussion or pull request for a security
problem. Report it privately instead:

- **Preferred:** [report a vulnerability](https://github.com/wardenbot-ai/pytest-wardenbot/security/advisories/new)
  through GitHub's private vulnerability reporting. The report stays private
  between you and the maintainers until a fix is published.
- **Email:** `mike@wardenbot.ai`, with "pytest-wardenbot security" in the
  subject.

Include the affected version, what an attacker could do, and steps or code to
reproduce it. A minimal test case is the most useful thing you can send.

## What to expect

pytest-wardenbot is maintained by a small team, so these are targets, not
guarantees:

| Step | Target |
|---|---|
| Acknowledge your report | 3 business days |
| Initial assessment (confirmed, severity, or not a vulnerability) | 10 business days |
| Fix or mitigation for a confirmed high or critical issue | 30 days |
| Public disclosure | When the fix ships, or 90 days after the report if no fix is ready, whichever is first |

We keep you updated as we go, agree the disclosure date with you, and credit
you in the advisory and release notes unless you prefer to stay anonymous.
Fixes ship as a patch release with a GitHub security advisory and, where it
applies, a CVE.

## Supported versions

pytest-wardenbot is in Beta. Security fixes go to the latest 0.x minor
release. See the [versioning and stability policy](docs/reference/stability.md).

## Scope

In scope:

- The `pytest-wardenbot` package on PyPI and its source in this repository,
  including the shipped tests, scenarios, harness and graders.
- Files the plugin generates, such as the `--wardenbot-quickstart` templates.
- This repository's GitHub Actions workflows and release process.

Examples of what we want to hear about: a grader that passes a response it
should fail in a way that hides a real leak or violation, harness or evidence
handling that can be made to report `resisted` for a violation, code
execution from crafted evidence bundles or scenario files, secrets written to
reports or logs, and weaknesses in how releases are built and published.

Out of scope here (report through [wardenbot.ai/.well-known/security.txt](https://wardenbot.ai/.well-known/security.txt)):

- The WardenBot AI managed service, website and hosted infrastructure.

Also out of scope: findings that need a malicious `conftest.py` or plugin
already running in your test process (it can do anything pytest can), and
vulnerabilities in dependencies that don't affect how pytest-wardenbot uses
them (report those upstream).

## Safe harbor

We won't pursue or support legal action against you for security research on
pytest-wardenbot that you conduct in good faith and in line with this policy.
That means testing against your own installations and test systems, not other
people's data or services; making a good-faith effort to avoid privacy
violations and disruption; and giving us a reasonable chance to fix the issue
before you disclose it. If you're unsure whether something is in scope, ask
us first.

## How releases are protected

- Releases are published from GitHub Actions with PyPI Trusted Publishing; no
  long-lived PyPI token exists.
- A release needs a `v*` tag on a commit that is on `main` and has passed CI,
  and approval by a maintainer in the protected `pypi` environment.
- Release builds use hash-locked tools. Each release carries PEP 740
  attestations on PyPI, plus GitHub build-provenance and SBOM attestations
  (`gh attestation verify <file> --repo wardenbot-ai/pytest-wardenbot`).
- Every GitHub Action is pinned to a full commit SHA.
- Dependencies, including every declared floor, are audited for known
  vulnerabilities on each change and weekly.
