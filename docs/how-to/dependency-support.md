# Dependency support

The package declares Python 3.11 or later and pytest 8.1.1 or later. CI checks
Python 3.11, 3.12, and 3.13 with the newest stable pytest that pip resolves.
A separate Python 3.11 lane checks exactly pytest 8.1.1. Resolved versions are
printed in each CI run; the current lane moves as new stable versions ship.

Pytest 8.0.x has an upstream `--pyargs` collection regression that can fail on
unrelated protected directories. The floor is 8.1.1, which includes the fix;
8.1.0 was yanked. See the [pytest 8.1.1 changelog](https://docs.pytest.org/en/8.1.x/changelog.html#pytest-8-1-1-2024-03-08).

The minimum core lane uses pytest-asyncio 0.23.8 and pytest-cov 5.0.0 as its
test harness, rather than installing the dev extra. This checks the declared
core pytest floor without forcing newer requirements from development tools.
The `[async]` extra starts at pytest-asyncio 0.24, which requires pytest 8.2
or later ([pytest-asyncio 0.24 metadata](https://pypi.org/pypi/pytest-asyncio/0.24.0/json));
pip resolves the additional requirements when installing that extra.

## Optional SDKs

| Extra | Declared dependency floor | Validation |
| --- | --- | --- |
| `openai` | OpenAI 1.0 | Adapter tests use stub clients; real SDK coverage is tracked separately. |
| `anthropic` | Anthropic 0.30 | Adapter tests use stub clients; real SDK coverage is tracked separately. |
| `langchain` | langchain-core 0.3 | Adapter tests use stub objects; real SDK coverage is tracked separately. |
| `judge` | DeepEval 2.0 | CI runs the full suite with the current resolved judge extra. |

A dependency floor is a resolver constraint, not evidence that every release
above it has been tested. The adapter unit tests check request construction,
responses, errors, and conversation behavior without provider credentials.
The manual live-API smoke workflow checks selected installed SDKs against real
services and requires provider credentials; it is not the pull-request gate.

Before claiming a new SDK range, test the exact proposed minimum and a current
stable version with real SDK clients and local transports, record resolved
versions, and update this page and CI together. Test dependency resolution as
well as adapter behavior. Add bounds only when a reproduced incompatibility
justifies them. The judge extra has its own transitive requirements and should
be tested separately from the core minimum lane.

## Packaging and tooling

CI builds and verifies both the sdist and wheel. A fresh environment installs
the wheel and runs the packaged probes from an external consumer directory,
covering plugin entry-point discovery and consumer fixture configuration.

Ruff and Pyright are pinned to the same versions in the dev extra and
pre-commit hooks. Update both files together and review any resulting lint or
format changes. These tool pins are contributor tooling, not runtime limits.
