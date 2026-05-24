# pytest-wardenbot

[![CI](https://github.com/pardamike/pytest-wardenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/pardamike/pytest-wardenbot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/pardamike/pytest-wardenbot/branch/main/graph/badge.svg)](https://codecov.io/gh/pardamike/pytest-wardenbot)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](https://pypi.org/project/pytest-wardenbot/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE.md)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)
[![Powered by WardenBot AI](https://img.shields.io/badge/Powered_by-WardenBot_AI-purple)](https://wardenbot.ai)

Pytest plugin for testing chatbots and LLM apps — prompt injection, jailbreaks, system-prompt leaks, hallucinations, brand drift.

📖 **Documentation:** [pardamike.github.io/pytest-wardenbot](https://pardamike.github.io/pytest-wardenbot/)

> **Status: pre-release.** v0.1.0 is in active development. APIs may change before the first stable release.

---

## What it does

Run pytest against your chatbot and find out if it leaks its system prompt, complies with known jailbreaks, hallucinates business facts, or drifts from your brand voice.

- **Black-box.** Tests run against your live chatbot via HTTP, OpenAI API, Anthropic API, or any object you write a small adapter for.
- **Deterministic-first.** v0.1 ships tests that need zero LLM API spend — regex, substring, and schema checks. Optional LLM-judge tests (DeepEval) ship as an extra for semantic checks.
- **Agent-ready failures.** When a test fails, the failure message includes a structured Markdown remediation prompt you can paste into Cursor or Claude Code.

## Install

```bash
pip install pytest-wardenbot
```

Optional extras for LLM-judge tests or vendor-native adapters:

```bash
pip install "pytest-wardenbot[judge]"        # adds DeepEval for semantic checks
pip install "pytest-wardenbot[openai]"       # adds OpenAI Chat adapter
pip install "pytest-wardenbot[anthropic]"    # adds Anthropic Messages adapter
```

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
        request_field="message",
        response_field="reply",
    )
```

Then run the shipped tests with `pytest --pyargs pytest_wardenbot.tests`.

When a test fails, read the failure message, paste the agent-ready Markdown
into Cursor / Claude Code, ship the fix.

## What's in v0.1 (so far)

| Category | Count | Grading | Requires API key? |
|---|---|---|---|
| Prompt-injection / jailbreak resistance | 5 prompts × 2 checks | deterministic | no |
| System-prompt leak elicitation (dedicated extraction prompts) | 3 | deterministic | no |
| Refusal-bypass (roleplay / pretext / hypothetical framings) | 3 | deterministic | no |
| Off-topic deflection | 2 | deterministic | no |
| Business-truth verification (parametrized over your facts) | user-supplied | deterministic | no |
| Semantic checks via DeepEval (5 factories: equivalence, brand, hallucination, off-policy, refusal quality) | user-supplied | LLM-judge | yes, with `[judge]` extra |

That's **18 deterministic tests** out-of-the-box plus your business-truth + judge lists, all running in under a second against a real chatbot with zero LLM API spend (unless you've opted into the `[judge]` extra).

## How it's different from related tools

- **vs Promptfoo (now OpenAI):** Promptfoo is a developer testing CLI. We're a pytest plugin — same tool your existing test suite uses, same CI integration you already have.
- **vs DeepEval:** DeepEval focuses on evaluation metrics (faithfulness, relevancy). We focus on adversarial security probes (jailbreak, system-prompt leak, refusal-bypass) — different problem, complementary tool. (We use DeepEval under the hood for our optional semantic checks.)
- **vs Garak / PyRIT:** Garak and PyRIT are research-grade attack libraries. We package a curated subset as everyday pytest tests with clear failure messages.

## License

Apache 2.0. See [LICENSE.md](./LICENSE.md).

## Powered by

[WardenBot AI](https://wardenbot.ai) — continuous external monitoring for AI chatbots. The pytest plugin is the free, open-source slice of our test corpus. Want continuous monitoring across all your bots with daily probes and a dashboard? [Join the waitlist](https://wardenbot.ai/waitlist) for our managed service.
