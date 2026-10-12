# Changelog

All notable changes to `pytest-wardenbot` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Opt-in application packs for poisoned retrieval, persistent memory, synthetic
  tenant/role separation, and approval-before-write. A controlled local support
  application records actual operations and includes benign, vulnerable,
  resistant and no-exposure controls, with shared campaign accounting.
- Repeatable `--wardenbot-agent-pack` selection, pack metadata and required
  baseline/attack coverage. Existing users retain the default eight MCP scenarios.

- Portable versioned evidence bundles with corpus, target and configuration
  fingerprints, explicit grader versions and provenance. Strict offline loading,
  evidence re-grading, bound synthetic fixture replay and baseline comparisons
  distinguish saved observations from new execution and incomplete coverage.
- Standalone inert HTML and JUnit evidence reports, with separate security and
  task-utility results. A packaged local CLI and clean-install example need no
  optional dependencies or credentials.

- Bounded concurrent agent campaigns with global call/turn budgets, cooperative
  deadlines and cancellation cleanup, isolated factory-owned targets, explicit
  incomplete coverage and supplied usage accounting. Targets must opt in to
  instrumentation; actual observed violations survive later execution failures.
- Explicit safe rate-limit retries with call accounting and stable keys for
  provider-deduplicated writes. Operations are never retried by default.
- Bounded async chatbot probes with isolated sessions, ordered per-input outcomes,
  supplied usage, and cleanup. Real MCP/reference examples exercise campaign caps
  without provider requests.

### Fixed

- Runtime `__version__` now comes from installed package metadata, avoiding drift
  between public reports and the distributed package version.

## [0.2.0] — 2026-10-11

### Added

- Separate packaged `pytest_wardenbot.agent_tests` suite with eight versioned
  scenarios: forbidden-tool and synthetic-canary assertions across tool results,
  descriptions, resources and prompts. Each scenario runs a benign baseline
  and an attack trial with independent task-utility checks.
- Explicit scenario selection, capability markers, sanitized console/JUnit
  diagnostics and required-coverage mode. Skipping or deselecting required
  cases, missing evidence and unsupported capabilities cannot silently pass CI.
  Baseline utility is distinguished from observed attack resistance.
- Real Responses/MCP reference agent with a dispatch allowlist and an
  intentionally vulnerable profile. Offline SDK controls run without API keys;
  opt-in live evaluation uses frozen development/holdout cases, repeated paired
  trials, request/output/time bounds and content-minimized reports.
- Benign MCP harness mode and configurable synthetic document/injection content
  for paired controls. Existing harness behavior remains the default.

### Fixed

- HTTP, OpenAI Chat and Anthropic infrastructure errors no longer include URL
  credentials, response bodies or raw provider exception text. HTTP reprs hide
  endpoints; malformed vendor output cannot leak through validation errors.
- Responses replay uses wire aliases and only fields present in the provider
  response. SDK-only names and unset defaults cannot leak into the next request;
  reasoning items remain intact for local replay.
- Owned sync/async clients now have explicit cleanup methods; injected vendor
  clients remain caller-owned. Examples and generated HTTP fixtures close their
  clients after use. Cancellation continues to propagate.
- Numeric business-fact checks no longer accept a prefix of a larger number or
  an unrelated in-range value among ambiguous numbers. `numeric_pattern` with a
  named `value` group supports scoped extraction. Existing multi-number checks
  may need this explicit selector; see the business-truth migration note.
- Documentation now states the limits of lexical fact matching and removes an
  unsupported calibration claim from the historical evaluation discussion.

The existing chatbot test package remains separate. The agent workflow records
local instrumented boundaries and includes deliberately vulnerable controls;
neither passing controls nor the small pilot establish general model security.

## [0.1.9] — 2026-10-11

### Added

- Transport-independent `AgentTarget`, `Scenario`, `HarnessTrace` and `RunResult`
  contracts, with explicit violated/resisted/inconclusive/unsupported/error
  outcomes. Task success remains separate from observed security behavior.
- Bounded async trial runner with unique trial IDs, reset before and after,
  execution/cleanup deadlines and cooperative turn limits. Authoritative local
  effects remain findings even if execution subsequently fails.
- Evidence provenance and scenario/version binding. Target-reported events
  cannot promote themselves into trusted observations or prove injected-content
  exposure. Missing coverage cannot silently become observed resistance.
- Content-minimized console, JSON and escaped HTML diagnostics. Optional content
  capture filters configured literals and sensitive keys; exception messages are
  replaced with fixed reason codes. Explicit deprecated conversion to legacy
  boolean results rejects incomplete/error outcomes.
- Optional `[mcp]` controlled harness with isolated recording sinks and real
  in-memory, stdio and loopback HTTP transports. Scripted controls exercise tool
  results, tool descriptions, resources and prompts across the tested
  2025-11-25 and 2026-07-28 protocol modes without provider credentials.
- MCP dependency-floor/current CI, lifecycle and cancellation regressions,
  a fresh-wheel MCP consumer check, and executable examples/documentation.

The existing chatbot interfaces and text suite remain compatible. This release
delivers the agent contracts and controlled harness; the packaged agent scenario
suite and a live application pilot remain subsequent roadmap work.

## [0.1.8] — 2026-10-11

### Added

- Sync and async OpenAI Responses text adapters with locally isolated session
  history, reset, serialized same-session calls and cancellation handling.
  Requests use `store=False`, repeat instructions and replay complete output
  items. Encrypted reasoning is retained for replay and redacted from public
  raw payloads by default. Incomplete or tool output raises infrastructure errors.
- Executable Responses example and migration guide for retired Assistants APIs.
- LangChain input mapping, configurable session keys and explicit reset hooks,
  plus a tested LangGraph checkpoint/thread isolation recipe. One-shot calls
  to stateful runnables use temporary sessions and clean up after completion.
- Offline contract tests with real OpenAI, Anthropic, LangChain and DeepEval
  SDKs at exact minimum and current versions; CI runs the current graph recipe.
- Opt-in community release/CI webhooks for Slack and Discord with a no-send
  preview, independent delivery results and setup instructions (#9).

### Changed

- Default Assistants constructors now fail with migration guidance before
  importing an SDK or making a request. Existing classes remain importable;
  explicitly injected compatible legacy clients remain available with a warning.
- Unknown LangChain outputs and invalid text extractors now raise infrastructure
  errors. Stateful reset requires a hook that clears the backing history.
- OpenAI extra now requires SDK 1.66.3 or later for Responses; Anthropic requires
  0.49.0 or later for compatible client construction and judge request fields.
- The judge extra requires DeepEval 4.2.8 and includes the Anthropic SDK needed
  by its default provider. DeepEval 2.0 lacks the required vendor wrappers.
  Compatibility tests exercise the built-in judge provider path. Requested
  temperature reaches current Anthropic SDKs through `extra_body` when the
  selected model supports it.

### Fixed

- The sync bridge now keeps one event loop for the lifetime of its wrapper,
  allowing async SDK connections to survive successive requests. Use its
  context manager or `close()` to clean up the loop and supported adapter resources.
- Generated quickstart fixtures now fail setup on missing or empty `CHATBOT_URL`,
  preventing an unconfigured consumer from returning a successful all-skipped run.
- Empty-string session IDs now preserve history in OpenAI Chat and Anthropic
  adapters, consistent with reset behavior and other non-None session IDs.
- Failure-triage documentation now distinguishes exception types from pytest's
  setup/call outcome labels, and explains the limits of payload redaction.

### Validation

Responses passed a bounded live API round trip on 11 October 2026. Its offline
contract tests also exercise the minimum and current SDK versions without credentials.
Community posting remains disabled until maintainers configure webhook secrets
and explicitly enable the workflow; no live channel delivery is claimed.

## [0.1.7] — 2026-10-11

### Fixed

- Restored consumer root fixtures when running the installed probe suite with
  `--pyargs` on pytest 9.1, preserving parametrization, scope and teardown.
- Raised the pytest floor to 8.1.1: 8.0.x can fail external `--pyargs`
  collection on unrelated protected directories (upstream pytest #11904).
  CI and installed-wheel checks test 8.1.1 explicitly.
- Missing required `chatbot` configuration now produces setup errors and a
  nonzero exit instead of an entirely skipped, successful security run.
- Updated Anthropic adapters for current SDKs: sampling parameters are omitted
  by default; an explicit `temperature` uses `extra_body` for older models that
  still support it. Explicit settings are not silently discarded.

### Maintenance

- Aligned Ruff and Pyright versions between CI and contributor hooks.
- Added minimum/current pytest coverage and fresh-wheel consumer checks for
  configured, vulnerable and missing-configuration cases.
- Added strict documentation validation and a dependency support policy.
- Split live provider checks into independent jobs with request timeouts,
  retry/output bounds and explicit missing-credential failures. Both providers
  passed bounded local round trips on 11 October 2026.

## [0.1.6] — 2026-10-11

Version 0.1.5 was tagged but did not reach PyPI: the old upload action rejected
core metadata 2.5. This release includes the ownership updates and upgrades the
SHA-pinned upload action to 1.14.2, which supports that metadata version.

### Fixed

- Updated repository, issue, contribution, badge, and documentation links after
  moving the project to `wardenbot-ai/pytest-wardenbot`.
- Refreshed PyPI project metadata without changing the package name or imports.
- Rebuilt the custom-domain docs and GitHub Pages fallback with deployment
  checks for navigation, assets, and ownership links.
- Documented the new PyPI Trusted Publisher settings and release procedure.

### Known maintenance work

This is an ownership and documentation release; runtime behavior and dependency
requirements are unchanged. The following existing issues were identified during
transfer verification and are deferred to the next maintenance phase:

- **pytest 9.1 compatibility:** the `--pyargs` integration path skips
  caller-configured fixtures with pytest 9.1.1 (23 integration tests fail).
  The full suite passes with pytest 9.0.3. Use the quickstart's local test file
  pattern while this is investigated.
- **Development tooling drift:** CI installs an unbounded Ruff version while
  pre-commit pins 0.15.14. Newer formatting rules fail on existing Markdown
  code examples; align the tools during the maintenance update.
- **Live vendor smoke checks:** scheduled OpenAI/Anthropic API runs were already
  failing before this transfer. Review credentials, supported APIs, and model
  selections before treating those adapters as recently live-verified.

## [0.1.4] — 2026-05-26

### Added

- **Bundled LangChain adapter** (`[langchain]` extra) — `LangChainAdapter` /
  `AsyncLangChainAdapter` wrap any LangChain Runnable (`.invoke` / `.ainvoke`).
  Duck-typed (never imports `langchain`), so it stays resilient across LangChain
  releases; extracts text from a string, a message `.content`, or a dict output
  key. (#3)
- **Multi-judge ensemble mode** — `judge_ensemble` / `assert_judge_ensemble_passes`
  grade one `JudgeCase` across several judge models and combine the verdicts
  under a consensus policy (`majority` default, `unanimous`, or `any`), set via
  the `--wardenbot-judge-consensus` option / `wardenbot_judge_consensus` fixture.
  Default panel is one popular model per vendor (claude-haiku-4-5, gpt-4o-mini,
  gemini-2.0-flash), routed to its SDK by name prefix. (#6)
- **Parallel async probe runner** — `pytest_wardenbot.runners.run_probes` fans a
  corpus out against an `AsyncChatbotAdapter` concurrently (semaphore-bounded),
  returning per-prompt results in input order; per-probe infra errors are
  captured rather than sinking the batch. New `[async]` extra + a "Run probes in
  parallel" how-to. (#2)

### Documentation

- Filled in the `docs/about/evaluation.md` result tables from a live run
  (gpt-4o-mini 28/29; claude-haiku-4-5 26/29 — decoded ROT13/leet/hex;
  vulnerable-stub 0/29). (#19)

## [0.1.3] — 2026-05-26

### Added

- Multi-turn jailbreak test now emits a `UserWarning` when it runs against an
  adapter that has not declared `stateful = True` — priming silently no-ops on a
  stateless adapter, so the test would otherwise pass trivially. Bundled SDK
  adapters (OpenAI Chat / Assistants, Anthropic) declare it; `HTTPChatbotAdapter`
  / `AsyncHTTPChatbotAdapter` take a `stateful=` flag for session-aware
  endpoints. (#18)

### Removed

- `pytest_wardenbot.remediation` (`Remediation` / `to_agent_markdown`) — an
  unused v0.1 formatter superseded by the internal failure-message builder the
  shipped tests actually use. It was never wired into the failure path, and its
  presence in the API reference misrepresented how remediation is emitted. (#20)

### Documentation

- New "Triage a failing test" how-to: ERROR vs FAILURE, failure-message anatomy,
  expected non-findings, and the fix loop. (#17)

## [0.1.2] — 2026-05-26

### Fixed

- **Indirect-injection (XPIA) false negative.** `test_resists_indirect_injection`
  graded responses only with the generic jailbreak / system-prompt-leak
  patterns, so the two corpus entries that smuggle a literal compliance token
  (`COMPROMISED`, `JAILBROKEN`) could be obeyed by the bot and still pass. The
  test now also checks for the smuggled trigger token (mirroring the
  encoded-payload test), so a bot that acts on the injection fails. The
  indirect-injection corpus entry shape is now `(prompt, trigger_words, attack_id)`.

### Changed

- **Documentation accuracy.** Corrected the shipped deterministic test count to
  29 (was overstated as 30); documented the bundled `OpenAIAssistantsAdapter` /
  `AsyncOpenAIAssistantsAdapter` (`[openai]` extra); fixed the
  `HTTPChatbotAdapter` default `response_field` shown in examples (`response`);
  corrected the fixture→test-name mapping in the corpus customization guide;
  fixed the encoded-payload encodings list (hex, not Unicode-tag); and removed
  stale "single-turn only" claims (multi-turn tests ship in v0.1). Added a
  "Verified adapters" note: the OpenAI + Anthropic adapters are smoke-tested
  weekly against the live vendor APIs.

## [0.1.1] — 2026-05-26

### Fixed

- Shipped tests now keep their parametrization when imported into your own test
  module — the pattern used by the bundled examples and `--wardenbot-quickstart`
  output. Previously, importing a corpus-driven test (e.g.
  `test_resists_jailbreak_compliance`) lost its `prompt`/`attack_id`
  parametrization, so the test errored with `fixture 'prompt' not found` once a
  `chatbot` fixture was wired up (the parametrizing hook was defined per-module
  and did not follow the import). Parametrization is now applied by a single
  global `pytest_generate_tests` hook keyed on the test name. Corpus overrides
  via the `wardenbot_*_prompts` fixtures are unchanged.

## [0.1.0] — 2026-05-24

Initial public release.

The docs site is published on every push to `main` via
[the docs workflow](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/docs.yml).

Releases to PyPI happen on tag push (`v*`) via
[the release workflow](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/release.yml)
using PyPI Trusted Publishing — no long-lived API tokens.

### Added (across the v0.1 development cycle)

- **Core plugin and adapter framework** — `ChatbotAdapter` and
  `AsyncChatbotAdapter` Protocols, `ChatbotResponse` model, bundled
  `HTTPChatbotAdapter` / `AsyncHTTPChatbotAdapter`, `AttackRunner`
  Protocol stub for v0.2.
- **Bundled vendor adapters** — `OpenAIChatAdapter` /
  `AsyncOpenAIChatAdapter` (via `[openai]` extra),
  `AnthropicMessagesAdapter` / `AsyncAnthropicMessagesAdapter` (via
  `[anthropic]` extra). All support optional session-keyed conversation
  memory.
- **Error taxonomy** — `WardenBotInfraError` distinguishes "bot is
  unreachable / malformed" (pytest ERROR) from "bot failed a check"
  (pytest FAILURE).
- **Response payload redaction** — `ChatbotResponse.raw` strips values
  whose keys look sensitive (authorization, api-key, cookie, etc.) by
  default. Opt out via `keep_sensitive_response_fields=True`.
- **29 deterministic shipped tests** (plus a parametrized business-truth
  test over your own facts):
    - 5 prompt-injection prompts × 2 checks (compliance + leak) = 10
    - 3 system-prompt elicitation tests
    - 3 refusal-bypass tests
    - 2 off-topic deflection tests
    - 4 indirect / cross-prompt injection (XPIA) tests
    - 4 encoded-payload jailbreak tests (Base64 / ROT13 / leet / hex)
    - 3 multi-turn jailbreak tests (priming + payload, needs
      session-aware adapter)
- **Canary-token leak detection** — opt-in `test_canary_leak` test +
  `pytest_wardenbot.canary` module. Strongest single signal for
  system-prompt disclosure.
- **Per-corpus override fixtures** — `wardenbot_jailbreak_prompts`,
  `wardenbot_off_topic_prompts`, etc. Users override in their
  `conftest.py` to substitute or extend any attack corpus.
- **Optional LLM-judge tests** — 5 case factories (semantic equivalence,
  brand alignment, hallucination grounding, off-policy, refusal quality)
  via the `[judge]` extra (DeepEval-backed).
- **Quickstart CLI** — `pytest --wardenbot-quickstart [TEMPLATE]`
  generates a starter `conftest.py` + `test_my_bot.py`. Three templates:
  `generic`, `ecommerce`, `saas-support`. Generated conftest skips
  cleanly when `CHATBOT_URL` is unset.
- **Pytest markers** — `wardenbot`, `severity_high`, `severity_medium`,
  `severity_low`.
- **Documentation site** — mkdocs-material, deployed to GitHub Pages.
- **Examples** — basic HTTP, OpenAI Chat, Anthropic Messages, custom
  adapter (for chatbots with middleware), GitHub Actions workflow.
- **CI** — lint (ruff), format (ruff), typecheck (pyright), test matrix
  across Python 3.11 / 3.12 / 3.13, build verification (twine), Codecov
  upload.
- **Repository hygiene** — pre-commit hooks (including `detect-secrets`),
  issue templates, PR template, CONTRIBUTING / CODE_OF_CONDUCT /
  SECURITY .md.

### Not yet (planned for v0.2+)

- Native-async shipped tests for parallel probe fan-out
- Bundled LangChain / MCP adapters
- Broader XPIA coverage via RAMPART (`[agentic]` extra)
- Multi-judge ensemble mode for safety-critical scoring
- Authenticated managed-service mode that uploads results to a WardenBot
  AI dashboard
