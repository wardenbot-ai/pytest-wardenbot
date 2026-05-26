# Changelog

All notable changes to `pytest-wardenbot` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

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
[the docs workflow](https://github.com/pardamike/pytest-wardenbot/actions/workflows/docs.yml).

Releases to PyPI happen on tag push (`v*`) via
[the release workflow](https://github.com/pardamike/pytest-wardenbot/actions/workflows/release.yml)
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
- **30 deterministic shipped tests**:
    - 5 prompt-injection prompts × 2 checks (compliance + leak) = 10
    - 3 system-prompt elicitation tests
    - 3 refusal-bypass tests
    - 2 off-topic deflection tests
    - 4 indirect / cross-prompt injection (XPIA) tests
    - 4 encoded-payload jailbreak tests (Base64 / ROT13 / leet / hex)
    - 3 multi-turn jailbreak tests (priming + payload, needs
      session-aware adapter)
    - 1 parametrized business-truth test (user-supplied facts)
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
