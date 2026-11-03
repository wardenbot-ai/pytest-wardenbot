# Versioning and stability

`pytest-wardenbot` is in **Beta** as of 0.4.0. The features planned for the
first stable release have shipped: the chatbot suite, instrumented agent
scenarios, application packs, bounded campaigns and portable evidence. The
public API below is meant to last. During 0.x it can still change, but only
under the rules on this page.

The project is not 1.0 yet because the agent contracts and evidence format are
new and few users outside the project have run them in CI. Beta feedback is
how we find out what needs to change before we commit to it. Please share it
in [GitHub Discussions](https://github.com/wardenbot-ai/pytest-wardenbot/discussions).

## What the policy covers

**Public API:**

- Names listed in `__all__` of `pytest_wardenbot`, `pytest_wardenbot.adapters`,
  `pytest_wardenbot.agents` and `pytest_wardenbot.agents.packs`, plus the
  vendor adapters documented in the [API reference](api.md).
- Command-line options (`--wardenbot-*`), [pytest markers](markers.md) and the
  fixture names the plugin asks you to provide.
- Shipped test node names and versioned scenario IDs, such as
  `application.retrieval.poisoned-document@1`.
- `Outcome` and `ReasonCode` values, and the meaning of each outcome.
- The evidence bundle schema (`EVIDENCE_SCHEMA_VERSION`) and the JSON written
  by the public report functions.

**Not public API:**

- Modules and names starting with an underscore.
- Everything under `examples/` and `scripts/`.
- The wording of failure messages, HTML report styling and corpus text.
  Scenario versions bind corpus text, as described below.

## Rules during 0.x

**Patch releases (0.4.x)** contain fixes, documentation, dependency-range
updates and new **opt-in** scenarios. They never remove or rename public API.
They never change the default scenario selection. They never change grading
in a way that could turn a failing run into a passing one.

**Minor releases (0.5, 0.6, …)** may change public API, but only after
deprecation. A deprecated item emits `DeprecationWarning` for at least one
full minor release before it is removed. Both the deprecation and the removal
are listed in the changelog. Two cases are exempt and are called out in the
changelog when they happen:

- security fixes;
- retirement of an upstream service, such as the OpenAI Assistants API.

**Scenarios are immutable per version.** The payload, assertions and required
evidence of `scenario@N` never change. Any change ships as `scenario@N+1`. The
previous version stays selectable for at least one minor release after its
replacement ships. Changes to which scenarios run by default happen only in
minor releases.

**Grading changes are versioned.** If a change could make a result more
permissive (for example, turning `VIOLATED` or `INCONCLUSIVE` into `RESISTED`),
it is treated as breaking. It ships in a minor release with a new grader
version recorded in evidence.

**Evidence bundles.** Schema and grader versions change only in minor
releases, and the changelog lists those changes. Loading is strict: a bundle
whose schema or grader version doesn't match is rejected, never guessed at.
Re-grade saved evidence with the release that wrote it.

## Supported versions

Fixes and security updates go to the latest 0.x minor release. Python
3.11–3.13 are supported. Tested dependency floors and ranges are listed in
[dependency support](../how-to/dependency-support.md).

## Current deprecations

- `to_legacy_attack_result` (deprecated in 0.1.9) bridges agent results to the
  reserved legacy `AttackResult`. Use `RunResult` directly.
- The OpenAI Assistants adapter classes remain importable for injected test
  clients. The public service is retired, so their default constructors fail.
  See [OpenAI migration](../how-to/migrate-openai.md).

## Toward 1.0

1.0 needs agent targets running in outside projects' CI, one minor release
cycle without breaking changes to the agent contracts or evidence schema, and
evidence loading that can read the previous schema version. From 1.0 on,
semantic versioning applies strictly: no breaking changes within a major
version, and deprecation warnings before every major release.
