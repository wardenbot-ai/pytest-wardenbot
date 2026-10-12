# pytest-wardenbot

Pytest security tests for chatbots and tool-using agents. Run a curated test suite
against your application to catch behavior regressions before your customers do.

!!! note "Pre-release"
    The 0.2 series is in active development. APIs may change before the first stable
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

## Test an agent's tool boundary

The agent suite adds eight versioned scenarios covering tool results,
descriptions, resources and prompts. Each has a benign baseline. Trusted
instrumentation records effects separately from model claims, and missing
exposure remains inconclusive. Required-coverage mode returns nonzero when a
selected scenario is skipped, deselected or lacks evidence.

Opt-in application packs extend this to poisoned retrieval, cross-session memory,
synthetic tenant/role separation and approval-before-write. These require explicit
application hooks and cover the declared local boundary.

[Configure agent scenarios →](how-to/agent-scenarios.md){ .md-button }
[Run the reference agent →](how-to/reference-agent.md){ .md-button }
[Test application boundaries →](how-to/application-packs.md){ .md-button }

The MCP harness runs locally without API credentials. The reference agent's
live mode is opt-in and makes bounded provider calls; its offline controls
exercise the same tool loop without network requests.

## What "passing" means (and doesn't)

A green run means your chatbot didn't fail any of the bundled 29 attacks
in the most overt way. It's a useful smoke test and a regression detector
— if a deploy turns a green test red, that's a real signal to investigate.

A green run does **not** mean your chatbot is secure. Frontier-grade
attacks are multi-turn, novel, and adapted to your specific bot — no fixed
corpus catches all of them. Treat the shipped suite as a starter set: pair
it with periodic red-team exercises (or our
[Continuous Monitoring](https://wardenbot.ai/intake/) service) for the
always-on adversarial coverage CI alone can't provide.

## How it compares

- **vs Promptfoo ([acquired by OpenAI in Feb 2026](https://openai.com/index/openai-to-acquire-promptfoo/)):**
  Promptfoo is a developer testing CLI. We're a pytest plugin — same test
  runner your existing suite uses, same CI integration you already have.
  Same idea, different shape.

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
a dashboard, and alerts?
[Tell us about your setup](https://wardenbot.ai/intake/).
