# pytest-wardenbot

Pytest plugin for testing chatbots and LLM apps — prompt injection, jailbreaks, system-prompt leaks, hallucinations, brand drift.

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

## Quickstart

1. Install the plugin:
   ```bash
   pip install pytest-wardenbot
   ```

2. Tell the plugin where your chatbot is. Add this to your project's `conftest.py`:

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

3. Run the shipped tests:
   ```bash
   pytest --pyargs pytest_wardenbot.tests
   ```

4. Read the failures, paste the agent-ready Markdown into your IDE, ship the fix.

## What's in v0.1 (so far)

| Category | Count | Grading |
|---|---|---|
| Prompt-injection / jailbreak resistance | 5 prompts × 2 checks | deterministic |
| System-prompt leak elicitation | (covered above) | deterministic |
| Optional semantic checks via DeepEval | 5 (landing later in v0.1 cycle) | LLM-judge |

## How it's different from related tools

- **vs Promptfoo (now OpenAI):** Promptfoo is a developer testing CLI. We're a pytest plugin — same tool your existing test suite uses, same CI integration you already have.
- **vs DeepEval:** DeepEval focuses on evaluation metrics (faithfulness, relevancy). We focus on adversarial security probes (jailbreak, system-prompt leak, refusal-bypass) — different problem, complementary tool. (We use DeepEval under the hood for our optional semantic checks.)
- **vs Garak / PyRIT:** Garak and PyRIT are research-grade attack libraries. We package a curated subset as everyday pytest tests with clear failure messages.

## License

Apache 2.0. See [LICENSE.md](./LICENSE.md).

## Powered by

[WardenBot AI](https://wardenbot.ai) — continuous external monitoring for AI chatbots. The pytest plugin is the free, open-source slice of our test corpus. Want continuous monitoring across all your bots with daily probes and a dashboard? [Join the waitlist](https://wardenbot.ai/waitlist) for our managed service.
