# Contributing to pytest-wardenbot

Thanks for being interested. This plugin is the open-source slice of
[WardenBot AI](https://wardenbot.ai)'s test corpus — the bar for contributions
is high because every shipped test is something users will run against their
production chatbots.

## Setup

```bash
git clone https://github.com/pardamike/pytest-wardenbot.git
cd pytest-wardenbot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Run the full check pipeline locally:

```bash
ruff check . && ruff format --check .   # lint + format
pyright                                  # typecheck
coverage run -m pytest                   # tests
coverage report --fail-under=80          # coverage gate
```

## What's in scope vs. out of scope

This is a **client-side pytest plugin**. It runs locally on the contributor's
machine, hits chatbots over the network, and produces pass/fail. Things that
need a backend live in the managed [WardenBot AI](https://wardenbot.ai) service,
not the plugin.

### In scope

- New shipped tests (more probes, better detection patterns)
- New chatbot adapters (`adapters/<vendor>.py`)
- Better grading helpers (deterministic and LLM-judge)
- DX improvements (`--wardenbot-quickstart` templates, examples)
- Documentation

### Out of scope

These belong in the managed service, not the OSS plugin. PRs that add these
will be politely declined:

- Cross-run history / dashboards
- Alert routing (Slack / webhook / email on regression)
- Scheduled / recurring runs against your chatbot
- LLM-judge result aggregation across customers
- Customer accounts / auth / billing
- Anything that requires a server we run

If your idea is in the second bucket, the right home is
https://wardenbot.ai/waitlist for the managed service.

## Code style

- **Plain English.** Variable names that read like sentences. Comments that
  explain *why*, not *what* — the code already says what.
- **Sync over async.** v0.1 is sync; async lands in v0.2 with a clear migration
  path. Don't add async code without prior discussion.
- **Script-first / LLM-fallback.** Per the WardenBot AI doctrine, deterministic
  checks come first. Reach for LLM judging only when no deterministic check
  applies. See `15-continuous-monitoring.md §4.1` in the main wardenbot repo.
- **Conservative detection patterns.** False positives in safety tests erode
  trust faster than false negatives. Err on the side of missing a specific
  variant rather than firing on a non-issue.
- **No new dependencies without strong justification.** Each transitive dep is
  a supply-chain risk our users inherit.

## Writing a new shipped test

A good new test:

1. **Targets one vulnerability class.** Don't bundle "all the jailbreak patterns
   in one test"; one test per attack pattern.
2. **Lives in a parametrized fixture.** Each attack prompt becomes a test ID;
   failures cite the specific pattern.
3. **Has a deterministic detector.** Use `pytest_wardenbot.grading.deterministic`
   helpers where possible; fall back to LLM judge only for genuinely subjective
   checks.
4. **Has a structured failure message** that includes agent-ready remediation
   Markdown. See `_format_failure` in `grading/deterministic.py`.
5. **Is covered by plugin self-tests** (`tests/test_plugin.py`) that verify
   it passes against a safe mock AND fails against a vulnerable mock.

## Pull request process

1. Fork + branch (`feat/<short-name>` or `fix/<short-name>`).
2. Make the change. Run the check pipeline locally.
3. Open a PR using the template. Make sure the scope-check boxes are honestly
   checked.
4. CI must be green before review (lint, typecheck, tests across 3.11/3.12/3.13,
   coverage ≥80%, build verifies wheel + sdist).
5. Expect ~1-business-day turnaround on the first review pass.

## Maintenance philosophy

- **No license rugpulls.** Apache 2.0, forever. HashiCorp / MongoDB / ElasticSearch
  taught the lesson; we won't repeat it.
- **No telemetry by default.** Ever. If we ever add opt-in telemetry, it'll be
  opt-in with the data shape documented in `SECURITY.md`.
- **Semantic versioning.** No breaking changes within a major. Major bumps come
  with 6-month deprecation warnings.
- **Monthly minor releases** on the second Tuesday: dependency updates, small
  test additions, bug fixes.

## Security

Don't open public issues for security reports. See [SECURITY.md](SECURITY.md)
for the private disclosure path.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
Be respectful. Don't be a jerk in code review.
