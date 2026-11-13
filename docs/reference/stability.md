---
description: Which names are public, what each kind of release may change, and current deprecations.
---

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

- Names listed in `__all__` of the modules below, imported from the module
  they are listed in. The [API reference](api.md) documents each of them.
- Type annotations of those names. The package ships `py.typed`, so type
  checkers read them. Patch releases may make an annotation more precise
  without changing behavior.
- Command-line options (`--wardenbot-*`), [pytest markers](markers.md), the
  `wardenbot_*` fixtures the plugin provides and the fixture names it asks you
  to provide.
- Shipped test node names, and the shipped test functions in
  `pytest_wardenbot.tests` and `pytest_wardenbot.agent_tests` that you can
  import into your own test module.
- Versioned scenario IDs, such as `application.retrieval.poisoned-document@1`.
- `Outcome` and `ReasonCode` values, and the meaning of each outcome.
- The evidence bundle schema (`EVIDENCE_SCHEMA_VERSION`) and the JSON written
  by the public report functions.

| Module | What it holds |
|---|---|
| `pytest_wardenbot` | Adapter protocols, the response type, business facts, judge cases and errors |
| `pytest_wardenbot.adapters` | HTTP adapters and the async-to-sync bridge |
| `pytest_wardenbot.adapters.base` | Adapter protocols and the response type |
| `pytest_wardenbot.adapters.http` | `HTTPChatbotAdapter` and its async version |
| `pytest_wardenbot.adapters.openai_responses` | OpenAI Responses adapters (`[openai]`) |
| `pytest_wardenbot.adapters.openai_chat` | OpenAI Chat Completions adapters (`[openai]`) |
| `pytest_wardenbot.adapters.openai_assistants` | Legacy Assistants adapters for injected clients |
| `pytest_wardenbot.adapters.anthropic_msgs` | Anthropic Messages adapters (`[anthropic]`) |
| `pytest_wardenbot.adapters.langchain_runnable` | LangChain Runnable adapters (`[langchain]`) |
| `pytest_wardenbot.local` | Ollama, vLLM and llama.cpp presets and the tool-calling check |
| `pytest_wardenbot.model` | The local model endpoint for deterministic pipeline tests |
| `pytest_wardenbot.model.mutate` | Mutators that turn a reply hostile, for `model_endpoint(mutate=...)` |
| `pytest_wardenbot.business_truth` | Business facts and their matcher |
| `pytest_wardenbot.canary` | Canary tokens |
| `pytest_wardenbot.corpus` | The attack prompts the shipped tests use |
| `pytest_wardenbot.grading` | Deterministic graders and the main judge helpers |
| `pytest_wardenbot.grading.deterministic` | Deterministic graders |
| `pytest_wardenbot.grading.judge` | LLM-judge helpers and ensembles (`[judge]`) |
| `pytest_wardenbot.runners` | Parallel async probes and the legacy runner protocol |
| `pytest_wardenbot.agents` | Agent contracts, runner, campaigns, evidence and reports |
| `pytest_wardenbot.agents.packs` | Application packs |
| `pytest_wardenbot.mcp` | The controlled MCP harness and `TrialTools` (`[mcp]`) |
| `pytest_wardenbot.targets.langgraph` | `LangGraphAgentTarget` (`[langgraph]`) |
| `pytest_wardenbot.targets.claude` | `ClaudeAgentTarget` (`[claude-agent]`) |

**Not public API:**

- Any module not in the table, even if its name has no underscore (for
  example `pytest_wardenbot.agents.contracts`). Import from the module in the
  table instead.
- Modules and names starting with an underscore.
- Everything under `examples/` and `scripts/`.
- The wording of failure messages, HTML report styling and corpus text.
  Scenario versions bind corpus text, as described below.

## Rules during 0.x

**Patch releases (such as 0.6.1)** contain fixes, documentation, dependency-range
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
it is treated as breaking. It ships in a minor release. Agent trials record a
new grader version in evidence. Chatbot tests have no evidence bundle, so
their grading changes are listed under "Changed (grading)" in the changelog,
and their measured accuracy is published on the
[grading accuracy](grading-accuracy.md) page.

**Evidence bundles.** Schema and grader versions change only in minor
releases, and the changelog lists those changes. Loading is strict: a bundle
whose schema or grader version doesn't match is rejected, never guessed at.
Re-grade saved evidence with the release that wrote it.

## Supported versions

Fixes and security updates go to the latest 0.x minor release. Python
3.11–3.14 are supported. Tested dependency floors and ranges are listed in
[dependency support](../how-to/dependency-support.md).

## Current deprecations

- `to_legacy_attack_result` (deprecated in 0.1.9) bridges agent results to the
  reserved legacy `AttackResult`. Use `RunResult` directly.
- The `test_canary_never_appears_in_responses` sweep (deprecated in 0.5.0,
  removed no earlier than 0.6.0). Every shipped leak check now tests the
  canary itself. See [Plant a canary token](../how-to/canary-token.md).
- Version 1 of the eight MCP scenarios (replaced by version 2 in 0.7.0, removed
  no earlier than 0.8.0). Select it by name, such as
  `mcp.tool-result.forbidden-tool@1`; see
  [scenario versions](../how-to/agent-scenarios.md#scenario-versions).
- The OpenAI Assistants adapter classes remain importable for injected test
  clients. The public service is retired, so their default constructors fail.
  See [OpenAI migration](../how-to/migrate-openai.md).

## Toward 1.0

1.0 needs agent targets running in outside projects' CI, one minor release
cycle without breaking changes to the agent contracts or evidence schema, and
evidence loading that can read the previous schema version. From 1.0 on,
semantic versioning applies strictly: no breaking changes within a major
version, and deprecation warnings before every major release.
