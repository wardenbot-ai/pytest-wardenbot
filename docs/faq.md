---
description: Answers to common questions about what the tests cover, cost and require.
---

# FAQ

## Does this actually run against my real chatbot?

Yes. The deterministic tests open an HTTP session (or call your custom
adapter) and send real prompts to your real bot. If you don't want that
in CI, you can use the included mock adapters in your own tests instead.

## Will running this cost me money?

Deterministic grading does not call a separate judge model. Your chatbot's
provider calls can still cost money. Optional LLM-judge checks add model calls;
see [Enable LLM-judge tests](how-to/llm-judge-setup.md) for the cost assumptions.

## Does it require Anthropic / OpenAI API keys?

Provider-backed chatbot adapters need their provider credentials, even when
grading is deterministic. HTTP adapters use the authentication your endpoint
requires. Separate judge credentials are needed for optional LLM-judge checks.

## My chatbot is general-purpose, not domain-scoped. Will the off-topic test fail?

Yes, by design. The off-topic test assumes a scoped customer-service or
support bot. If your bot is intentionally general-purpose, turn it off in
`conftest.py` by returning no prompts:

```python
import pytest


@pytest.fixture
def wardenbot_off_topic_prompts():
    return ()  # general-purpose bot: nothing is off-topic
```

Or deselect it for one run with `pytest -k "not off_topic"`. You can also
return your own prompts that are off-topic for your bot.

## What about agents that call tools?

Use the agent suite. It runs your agent against a controlled local MCP harness
that serves injected tool results, tool descriptions, resources and prompts,
and records every tool call the agent makes, including calls your own code
blocks. A trial fails only on a recorded forbidden call or leaked canary, not
on what the agent says. Start with `pytest --wardenbot-quickstart=agent`, then
connect [LangGraph](how-to/langgraph-agent.md),
[Claude Agent SDK](how-to/claude-agent.md),
[OpenAI Agents SDK](how-to/openai-agents.md) or
[your own tool loop](how-to/custom-agent.md).

The suite tests your agent, not your MCP servers. To scan servers and tool
definitions, use a scanner such as
[Snyk Agent Scan](https://github.com/snyk/agent-scan) or
[Cisco's MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner).

## My bot is behind a login. How do I test it?

Three options:

1. Provide a test user's session token via `CHATBOT_TOKEN` and put it in
   the `Authorization` header (the bundled `HTTPChatbotAdapter` does this
   pattern out of the box).
2. Write a custom adapter that performs the login flow first and then
   uses the resulting session cookie.
3. Have your platform team mint a permanent service-account token
   specifically for wardenbot testing.

## Can I test a Slack / Discord / Teams bot?

Write a small custom adapter: `send_message` posts the prompt as a test user
and returns the bot's reply, and `reset_session` starts a new thread. See
[Add your chatbot](how-to/add-chatbot.md). There are no bundled Slack,
Discord or Teams adapters, and none are planned for now.

## What model does the LLM judge use?

Claude Haiku 4.5 by default. Choose another with `--wardenbot-judge-model` or
`WARDENBOT_JUDGE_MODEL`, including a local model such as
`ollama/qwen2.5:7b`; see [Enable LLM-judge tests](how-to/llm-judge-setup.md).

## How reliable is the LLM judge?

Per published research, single LLM judges agree with human raters about
80% of the time on safety/quality scoring. Treat results as triage
signal, not absolute pass/fail. Ensemble mode is already available through
`judge_ensemble` and `assert_judge_ensemble_passes`; it combines multiple judges
without guaranteeing agreement with human reviewers.

## My CI keeps failing flakily on the same test.

Model output varies, so a check that usually passes can fail now and then.
Treat that as a finding: a bot that follows an injection one time in ten will
do it in production too. Don't retry failed security checks automatically.
Set the model's temperature to 0 where you can, and to measure how often
something happens, run repeated trials; see
[CI integration](how-to/ci-integration.md#when-a-result-changes-between-runs).

## Can I run this in parallel?

Yes, `pytest-xdist` works:

```bash
pip install pytest-xdist
pytest -n auto
```

Note that running many tests in parallel against the same chatbot
endpoint can hit rate limits on the chatbot side, which surfaces as
test failures. Tune `-n` accordingly.

## Why not just ship as a CLI tool?

A pytest plugin integrates with everything `pytest` does — fixtures,
parametrize, markers, your existing CI, your existing test runner,
your existing report format. A standalone CLI would reinvent all of
that. You probably already have pytest in your stack.

## Does this work with hosted chatbot platforms like Voiceflow / Intercom Fin?

The HTTP adapter works against any chatbot that has a JSON API endpoint.
For hosted platforms whose chatbots only have a web widget (no API), see
the managed [WardenBot AI](https://wardenbot.ai) service — it uses a real
browser to drive the widget, which is outside the OSS plugin's scope.

## How do I get help?

- [Open an issue](https://github.com/wardenbot-ai/pytest-wardenbot/issues/new/choose)
- Check the [examples](https://github.com/wardenbot-ai/pytest-wardenbot/tree/main/examples)
- For security reports, see [SECURITY.md](https://github.com/wardenbot-ai/pytest-wardenbot/blob/main/SECURITY.md)


## What happened to OpenAI Assistants?

OpenAI retired the public Assistants API on 26 August 2026. Use the bundled
Responses adapters; the legacy Assistants default constructors now fail with
migration instructions. See [OpenAI migration](how-to/migrate-openai.md) for
local histories, resets, and the limits of text-only adapters.

## How do I test LangGraph history?

Use the LangChain adapter with `session_config_key="thread_id"`, a messages
input mapper, a final-assistant text extractor, and a checkpointer reset hook.
The [LangGraph recipe](how-to/langgraph-state.md) demonstrates independent
threads and deletion with no LLM key. See
[dependency support](how-to/dependency-support.md) for tested SDK combinations.
