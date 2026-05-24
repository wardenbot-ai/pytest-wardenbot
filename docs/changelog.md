# Changelog

All notable changes to `pytest-wardenbot` are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased] — 0.1.0.dev0

The v0.1.0 line is the initial pre-release.

The docs site you're reading is published on every push to `main` via
[the docs workflow](https://github.com/pardamike/pytest-wardenbot/actions/workflows/docs.yml).

### Added (across the v0.1 development cycle)

- **Core plugin and adapter framework** — `ChatbotAdapter` Protocol,
  `ChatbotResponse` model, bundled `HTTPChatbotAdapter`, `AttackRunner`
  Protocol stub for v0.2.
- **18 deterministic shipped tests**:
    - 5 prompt-injection prompts × 2 checks (compliance + leak)
    - 3 system-prompt elicitation tests
    - 3 refusal-bypass tests
    - 2 off-topic deflection tests
    - 1 parametrized business-truth test (user-supplied facts)
- **Optional LLM-judge tests** — 5 case factories (semantic equivalence,
  brand alignment, hallucination grounding, off-policy, refusal quality)
  via the `[judge]` extra (DeepEval-backed).
- **Quickstart CLI** — `pytest --wardenbot-quickstart [TEMPLATE]`
  generates a starter `conftest.py` + `test_my_bot.py`. Three templates:
  `generic`, `ecommerce`, `saas-support`.
- **Pytest markers** — `wardenbot`, `severity_high`, `severity_medium`,
  `severity_low`.
- **Documentation site** — mkdocs-material, deployed to GitHub Pages.
- **Examples** — basic HTTP, custom OpenAI adapter, GitHub Actions
  workflow.
- **CI** — lint (ruff), format (ruff), typecheck (pyright), test matrix
  across Python 3.11 / 3.12 / 3.13, build verification (twine), Codecov
  upload.
- **Repository hygiene** — pre-commit hooks, issue templates, PR template,
  CONTRIBUTING / CODE_OF_CONDUCT / SECURITY .md.

### Not yet (planned for v0.2+)

- Bundled adapters for OpenAI Chat / Anthropic Messages / LangChain / MCP
- Cross-Prompt Injection Attack (XPIA) testing via RAMPART (`[agentic]` extra)
- Multi-turn attack chains beyond basic PyRIT integration
- Multi-judge ensemble mode for safety-critical scoring
- Authenticated managed-service mode that uploads results to a WardenBot
  AI dashboard
