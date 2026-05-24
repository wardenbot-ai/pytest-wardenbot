# pytest-wardenbot

Pytest plugin for testing chatbots and LLM apps. Run a curated test suite
against your chatbot to catch behavior regressions before your customers do.

!!! note "Pre-release"
    v0.1.0 is in active development. APIs may change before the first stable
    release. See the [changelog](changelog.md) for what's landed.

## Why this exists

You added a chatbot to your product. Now you want to know:

- Does it follow known prompt-override patterns?
- Does it ever reveal its system prompt?
- Does it stay polite when users push back?
- Does it remember your real prices, hours, and policies?
- Does it stay on-topic instead of writing essays about quantum physics?

`pytest-wardenbot` runs those checks as plain `pytest` tests against your
live chatbot. Failures include a structured Markdown block you paste into
Cursor or Claude Code to fix the issue.

## Two-minute tour

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart            # generates conftest.py + test_my_bot.py
export CHATBOT_URL=https://your-chatbot.example.com/chat
pytest
```

That's it. The shipped suite ran. Read the failures, paste the remediation
Markdown into your IDE, iterate.

[Full quickstart →](quickstart.md){ .md-button .md-button--primary }
[See what's tested →](tests/index.md){ .md-button }

## How it compares

- **vs Promptfoo (now OpenAI):** Promptfoo is a developer testing CLI.
  We're a pytest plugin — same test runner your existing suite uses, same
  CI integration you already have. Same idea, different shape.

- **vs DeepEval:** DeepEval focuses on evaluation metrics (faithfulness,
  relevancy). We focus on behavior testing (jailbreak resistance,
  system-prompt protection, brand drift). We use DeepEval under the hood
  for our optional LLM-judge tests.

- **vs Garak / PyRIT:** Garak and PyRIT are research-grade libraries. We
  package a curated subset as everyday tests with clear failure messages.

## Powered by

[WardenBot AI](https://wardenbot.ai) — continuous external monitoring for
AI chatbots. The pytest plugin is the free, open-source slice of our test
corpus. Want continuous monitoring across all your bots with daily probes,
a dashboard, and alerts? [Join the waitlist](https://wardenbot.ai/waitlist).
