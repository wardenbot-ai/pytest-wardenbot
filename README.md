# pytest-wardenbot

[![CI](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/wardenbot-ai/pytest-wardenbot/branch/main/graph/badge.svg)](https://codecov.io/gh/wardenbot-ai/pytest-wardenbot)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://pypi.org/project/pytest-wardenbot/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE.md)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

Pytest security tests for chatbots and tool-using agents — prompt injection,
MCP boundary checks, data leaks and semantic regressions.

📖 **Documentation:** [pytest-wardenbot.wardenbot.ai](https://pytest-wardenbot.wardenbot.ai/)

> **Status: pre-release.** The 0.2 series is in active development. APIs may change before the first stable release. Follow ongoing work in [GitHub Issues](https://github.com/wardenbot-ai/pytest-wardenbot/issues).

---

## What it does

Run pytest against your chatbot and find out if it leaks its system prompt, complies with known jailbreaks, hallucinates business facts, or drifts from your brand voice.

- **Black-box.** Tests run against your live chatbot via HTTP, OpenAI API, Anthropic API, or any object you write a small adapter for.
- **Deterministic-first.** v0.1 ships 29 tests graded with regex, substring, and schema checks, without a separate judge model. Your chatbot's API usage may still cost money. Optional LLM-judge tests (DeepEval) ship as an extra for semantic checks.
- **Agent-ready failures.** When a test fails, the failure message includes a structured Markdown remediation prompt you can paste into Cursor or Claude Code.
- **Public adapter checks.** The bundled OpenAI and Anthropic adapters have mock-based tests and a scheduled live API smoke workflow. Check the [latest workflow results](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/live-api-smoke.yml) for the current live status.
- **Instrumented agent scenarios.** Eight versioned cases cover MCP tool results,
  descriptions, resources and prompts, each with a benign baseline. A recording
  sink proves effects; required-coverage mode prevents missing evidence from
  becoming a successful CI run.

### What "passing" means (and doesn't)

A green run means your chatbot didn't fail any of the bundled 29 attacks in the most overt way. It's a useful smoke test and a regression detector — if a deploy turns a green test red, that's a real signal to investigate.

A green run does **not** mean your chatbot is secure. Frontier-grade attacks are multi-turn, novel, and adapted to your specific bot — no fixed corpus catches all of them. Treat the shipped suite as a starter set: pair it with periodic red-team exercises (or our [Continuous Monitoring](https://wardenbot.ai/intake/) service) for the always-on adversarial coverage CI alone can't provide.

## Install

Requires Python 3.11+. The package is maintained by
the [WardenBot AI organization](https://github.com/wardenbot-ai/pytest-wardenbot);
the GitHub transfer does not change its PyPI name or Python imports.

```bash
pip install pytest-wardenbot
```

Optional extras for LLM-judge tests or vendor-native adapters:

```bash
pip install "pytest-wardenbot[judge]"        # adds DeepEval for semantic checks
pip install "pytest-wardenbot[openai]"       # adds OpenAI Responses + Chat adapters (sync + async)
pip install "pytest-wardenbot[anthropic]"    # adds Anthropic Messages adapter (sync + async)
pip install "pytest-wardenbot[langchain]"    # adds LangChainAdapter for any Runnable (sync + async)
pip install "pytest-wardenbot[async]"        # adds pytest-asyncio for parallel async probing (run_probes)
pip install "pytest-wardenbot[mcp]"          # adds the controlled local MCP harness
```

> **Assistants retirement:** OpenAI retired the Assistants API on 26 August 2026;
> it is unavailable. Use `OpenAIResponsesAdapter` for new OpenAI text integrations.
> Legacy Assistants class names remain importable for explicitly injected test
> clients or compatible proxies; their default constructors fail before SDK or
> network calls. See [OpenAI migration](docs/how-to/migrate-openai.md).

| Integration | Adapter | Conversation state |
| --- | --- | --- |
| OpenAI Responses text | `OpenAIResponsesAdapter` / `AsyncOpenAIResponsesAdapter` | Local history per session; requests use `store=False`. |
| OpenAI Chat Completions text | `OpenAIChatAdapter` / `AsyncOpenAIChatAdapter` | Local history per session. |
| Checkpointer-backed LangGraph | `LangChainAdapter` / `AsyncLangChainAdapter` | Explicit thread key and reset hook; see [recipe](docs/how-to/langgraph-state.md). |
| Your deployed chatbot or agent | HTTP or custom adapter | Your application's conversation and tool flow. |

See the [dependency support matrix](docs/how-to/dependency-support.md) for
validated SDK combinations and [adapter setup](docs/how-to/add-chatbot.md).

### Instrumented agent trials

For larger runs, [bounded campaigns](docs/how-to/agent-campaigns.md) share call and
turn budgets across isolated trials, drain cooperative cancellation, and retain
every planned case in the report. Retries require an explicit safety declaration.

The additive `pytest_wardenbot.agents` API records explicit outcomes: violation,
observed resistance, inconclusive evidence, unsupported capabilities and execution
errors. A trusted recording sink establishes effects; model claims do not. Task
success is tracked separately, and diagnostic content is hidden by default.

The optional [MCP harness](docs/how-to/mcp-harness.md) exercises tool results,
tool descriptions, resources and prompts over real local MCP transports, with
scripted vulnerable/resistant/unexposed controls. It needs no provider credentials.
See [agent trials](docs/how-to/agent-trials.md) for the contract and application
integration responsibilities.

After configuring your `agent_target` and `agent_observer` fixtures:

```bash
pytest --pyargs pytest_wardenbot.agent_tests --wardenbot-agent-required
# Select one versioned scenario and its benign baseline:
pytest --pyargs pytest_wardenbot.agent_tests \
  --wardenbot-agent-scenario=mcp.tool-result.forbidden-tool@1 \
  --wardenbot-agent-required
```

The [scenario guide](docs/how-to/agent-scenarios.md) includes a complete local
fixture setup. The [reference agent](docs/how-to/reference-agent.md) and
[pilot methodology](docs/about/agent-pilot.md) exercise a bounded model/tool loop
with paired benign and attack trials. Existing chatbot tests remain in the
separate `pytest_wardenbot.tests` suite.


## Quickstart (under 60 seconds)

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart           # generates conftest.py + test_my_bot.py
export CHATBOT_URL=https://your-chatbot.example.com/chat
export CHATBOT_TOKEN=sk-...              # optional
pytest                                   # runs all shipped tests against your bot
```

`--wardenbot-quickstart` accepts an industry template:

```bash
pytest --wardenbot-quickstart=ecommerce       # adds refund/shipping fact placeholders
pytest --wardenbot-quickstart=saas-support    # adds plan/trial fact placeholders
pytest --wardenbot-quickstart=generic         # default; minimal placeholders
```

Then edit `conftest.py` to replace the TODO placeholders with your real
business facts and re-run `pytest`. Worked examples in [`examples/`](./examples/)
cover the basic HTTP setup, a custom OpenAI adapter, and a GitHub Actions
workflow.

### Manual setup (if you prefer)

Add this to your project's `conftest.py`:

```python
import os
import pytest
from pytest_wardenbot.adapters.http import HTTPChatbotAdapter

@pytest.fixture
def chatbot():
    return HTTPChatbotAdapter(
        url="https://your-chatbot.example.com/chat",
        headers={"Authorization": f"Bearer {os.environ['CHATBOT_TOKEN']}"},
        request_field="message",      # the JSON key your bot reads the prompt from
        response_field="response",     # the JSON key your bot returns the text in
    )
```

Then run the shipped tests with `pytest --pyargs pytest_wardenbot.tests`.

When a test fails, read the failure message, paste the agent-ready Markdown
into Cursor / Claude Code, ship the fix.

## What's in v0.1

| Category | Count | Grading | Requires API key? |
|---|---|---|---|
| Prompt-injection / jailbreak resistance | 5 prompts × 2 checks = 10 | deterministic | no |
| System-prompt leak elicitation (dedicated extraction prompts) | 3 | deterministic | no |
| Refusal-bypass (roleplay / pretext / hypothetical framings) | 3 | deterministic | no |
| Off-topic deflection (scoped bots) | 2 | deterministic | no |
| Indirect / cross-prompt injection (XPIA) | 4 | deterministic | no |
| Encoded-payload jailbreak (Base64 / ROT13 / leet / hex) | 4 | deterministic | no |
| Multi-turn jailbreak (priming + payload, needs session-aware adapter) | 3 | deterministic | no |
| Canary-token leak (opt-in; you plant the token) | 1 | deterministic | no |
| Business-truth verification (parametrized over your facts) | user-supplied | deterministic | no |
| Semantic checks via DeepEval (5 factories: equivalence, brand, hallucination, off-policy, refusal quality) | user-supplied | LLM-judge | yes, with `[judge]` extra |

That's **29 deterministic tests** out-of-the-box (plus the opt-in canary leak test, plus your business-truth and judge lists). Runtime and chatbot API costs depend on your endpoint; the deterministic checks do not call a separate judge model.

LangChain adapters, ensemble judging, and parallel async probes are available
in the 0.1 series. Follow upcoming work in
[GitHub Issues](https://github.com/wardenbot-ai/pytest-wardenbot/issues).

## How it's different from related tools

- **vs Promptfoo ([acquired by OpenAI in Feb 2026](https://openai.com/index/openai-to-acquire-promptfoo/)):** Promptfoo is a developer testing CLI. We're a pytest plugin — same tool your existing test suite uses, same CI integration you already have.
- **vs DeepEval:** DeepEval focuses on evaluation metrics (faithfulness, relevancy). We focus on adversarial security probes (jailbreak, system-prompt leak, refusal-bypass) — different problem, complementary tool. (We use DeepEval under the hood for our optional semantic checks.)
- **vs Garak / PyRIT:** Garak and PyRIT are research-grade attack libraries. We package a curated subset as everyday pytest tests with clear failure messages.

## License

Apache 2.0. See [LICENSE.md](./LICENSE.md).

## Powered by

[WardenBot AI](https://wardenbot.ai) — continuous external monitoring for AI chatbots. ![Powered by WardenBot AI](https://img.shields.io/badge/Powered_by-WardenBot_AI-purple)

The pytest plugin is the free, open-source slice of our test corpus. Want continuous monitoring across all your bots with daily probes and a dashboard? [Tell us about your setup](https://wardenbot.ai/intake/) — we open invites in small batches.
