# Contributing to pytest-wardenbot

Thanks for being interested. This plugin is the open-source slice of
[WardenBot AI](https://wardenbot.ai)'s test corpus — the bar for contributions
is high because every shipped test is something users will run against their
production chatbots.

## Setup

```bash
git clone https://github.com/wardenbot-ai/pytest-wardenbot.git
cd pytest-wardenbot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

The dev extra installs the same pinned Ruff and Pyright versions as the hooks.
Update their pins and hook revisions together, and review any formatting changes.

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
https://wardenbot.ai/intake/ for the managed service.

## Code style

- **Plain English.** Variable names that read like sentences. Comments that
  explain *why*, not *what* — the code already says what.
- **Explicit sync and async interfaces.** Keep adapter behavior consistent
  across both forms. Use the async probe runner when concurrency is needed.
- **Script-first / LLM-fallback.** Per the WardenBot AI doctrine, deterministic
  checks come first. Reach for LLM judging only when no deterministic check
  applies. See [the design principles doc](docs/about/design.md) for the rationale.
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
   coverage ≥80%, minimum/current pytest, strict docs build, wheel + sdist,
   fresh-wheel consumer).
   See [dependency support](docs/how-to/dependency-support.md) for the matrix.
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

## Releases and ownership

The repository is maintained at `wardenbot-ai/pytest-wardenbot`. The PyPI
project remains `pytest-wardenbot`; users keep installing it with
`pip install pytest-wardenbot`. A GitHub transfer does not move the PyPI
account or update the metadata of an already published release.

Before publishing from the new organization, a PyPI project owner must add a
GitHub publisher in the existing project's
[Publishing settings](https://pypi.org/manage/project/pytest-wardenbot/settings/publishing/):

| Field | Value |
|---|---|
| Owner | `wardenbot-ai` |
| Repository | `pytest-wardenbot` |
| Workflow | `release.yml` |
| Environment | `pypi` |

Use [PyPI's existing-project instructions](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
Do not create a second package or a pending publisher. Once a release from the
organization succeeds, remove the obsolete personal-repository publisher.
PyPI organization membership is separate and optional for this migration.

To release:

1. Update the version in `pyproject.toml` and `src/pytest_wardenbot/__init__.py`,
   and describe the changes in `docs/changelog.md`.
2. Run the checks above, `python -m build`, and `twine check --strict dist/*`
   using an empty output directory. Wait for CI on the release commit to pass.
3. Push an annotated `v<version>` tag on that commit. `release.yml` verifies
   the tag, builds distributions, and publishes with Trusted Publishing.
   To retry, rerun the failed job on the tag; do not dispatch from `main`.
4. Confirm the version and project links on
   [PyPI](https://pypi.org/project/pytest-wardenbot/), then test installation
   in a fresh virtual environment. The new release updates the PyPI page's
   README and repository links; old release metadata stays unchanged.

Docs deploy on `main` to the Cloudflare Pages project `pytest-wardenbot` at
<https://pytest-wardenbot.wardenbot.ai/> and, independently, to the GitHub Pages
fallback at <https://wardenbot-ai.github.io/pytest-wardenbot/>. Each deployment
runs the navigation and asset checks in `scripts/check_docs.py`. Keep the
Cloudflare account/token secrets available to this repository after transfers.
The GitHub Pages fallback uses the `github-pages` environment and Actions as
its publishing source; the custom domain belongs to Cloudflare.

## Security

Don't open public issues for security reports. See [SECURITY.md](SECURITY.md)
for the private disclosure path.

## Code of conduct

This project follows the [Contributor Covenant 2.1](CODE_OF_CONDUCT.md).
Be respectful. Don't be a jerk in code review.
