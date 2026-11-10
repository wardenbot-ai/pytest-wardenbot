# pytest-wardenbot

Pytest security tests for chatbots and tool-using agents. Run a curated test suite
against your application to catch behavior regressions before your customers do.

!!! note "Beta"
    The 0.4 series is in Beta. Public APIs change only under the
    [versioning and stability policy](reference/stability.md). Share feedback in
    [GitHub Discussions](https://github.com/wardenbot-ai/pytest-wardenbot/discussions);
    see the [changelog](changelog.md) for what's landed.

## Why this exists

You added a chatbot or a tool-using agent to your product. Now you want to know:

- Does it follow known prompt-override patterns, or reveal its system prompt?
- Does it remember your real prices, hours, and policies, and stay on-topic?
- When a tool result, retrieved document or stored memory carries untrusted
  instructions, does your agent act on them?
- Does it read, write and approve only within the boundaries you declared?

`pytest-wardenbot` runs those checks as plain `pytest` tests against your
live application. Chatbot failures include a structured Markdown block you can
paste into Cursor or Claude Code. Agent scenarios record what the agent
actually did, so a crossed boundary becomes a regression test you keep in CI.

## Two-minute tour (chatbot suite)

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
exercise the same tool loop without network requests. A second
[support application pilot](about/support-pilot.md) uses direct ticket APIs and
scoped approvals, with benign quoted/encoded text and repeated held-out trials.
Campaign limits and [portable evidence](how-to/evidence-bundles.md) make findings
reviewable across runs.

## What "passing" means (and doesn't)

A passing response check means it did not detect its configured failure pattern.
A required agent suite also needs complete declared-boundary evidence and
successful benign task controls. The [coverage matrix](about/coverage.md) maps
versioned scenarios to tested behavior and identifies untested risk categories.

A green run does **not** mean your chatbot is secure. Frontier-grade
attacks are multi-turn, novel, and adapted to your specific bot — no fixed
corpus catches all of them. Treat the shipped suite as a starter set: pair
it with periodic red-team exercises (or our
[Continuous Monitoring](https://wardenbot.ai/intake/) service) for the
always-on adversarial coverage CI alone can't provide.

## How it compares

Several good tools overlap with parts of this one. We aim to complement them.

- **Promptfoo** runs red-team and evaluation suites from a CLI, including MCP
  security testing. pytest-wardenbot runs inside the pytest suite and CI you
  already have, and its agent results come from what the harness recorded the
  agent attempting and doing, rather than the agent's final text.
- **RAMPART** also brings security testing to pytest, built on PyRIT's broader
  attack generation. pytest-wardenbot keeps a small core install and its own
  controlled harness, and adds versioned scenarios, required coverage and
  portable evidence.
- **DeepEval** and **Inspect AI** provide evaluation metrics and agent-evaluation
  infrastructure. pytest-wardenbot focuses narrowly on security regressions
  with explicit outcomes. It uses DeepEval for its optional semantic checks.
- **Garak** and **PyRIT** are broad attack and research libraries. The chatbot
  suite packages a curated set of test patterns as everyday pytest tests with
  clear failure messages.

## Powered by

[WardenBot AI](https://wardenbot.ai) — continuous external monitoring for
AI chatbots and agents. The pytest plugin is the free, open-source slice of our test
corpus. Want continuous monitoring across all your bots with daily probes,
a dashboard, and alerts?
[Tell us about your setup](https://wardenbot.ai/intake/).
