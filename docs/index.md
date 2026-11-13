# pytest-wardenbot

Pytest security tests for chatbots and tool-using agents: prompt injection,
system-prompt leaks, and agents acting on instructions hidden in tool results,
MCP resources and prompts. Agent results come from what a controlled harness
recorded the agent doing, not from what the agent says. Everything can run on
your machine, including against Ollama, vLLM or llama.cpp models with no API
key.

!!! note "Scope"
    pytest-wardenbot tests **your chatbot or agent, not your MCP server**. To
    scan MCP servers and tool definitions themselves, use a scanner such as
    [Snyk Agent Scan](https://github.com/snyk/agent-scan) or
    [Cisco's MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner).

## Test a chatbot

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart                  # writes conftest.py and test_my_bot.py
export CHATBOT_URL=https://your-bot.example.com/chat
pytest                                         # 29 checks, about 35 requests to your bot
```

Failures say what the bot did wrong and include a Markdown remediation brief
you can paste into Cursor or Claude Code.

[Chatbot quickstart →](quickstart.md#test-a-chatbot){ .md-button .md-button--primary }
[What the checks cover →](tests/index.md){ .md-button }

## Test an agent

```bash
pip install "pytest-wardenbot[mcp,openai]"
pytest --wardenbot-quickstart=agent            # writes conftest.py and test_my_agent.py
export OPENAI_API_KEY=sk-...                   # or: export AGENT_LOCAL=ollama AGENT_MODEL=qwen2.5:7b
pytest --wardenbot-agent-required              # 8 scenarios, each with a baseline and an attack
```

The generated agent is a working tool-calling loop, so the first run tests a
real model. Then connect your own:
[LangGraph](how-to/langgraph-agent.md),
[Claude Agent SDK](how-to/claude-agent.md),
[OpenAI Agents SDK](how-to/openai-agents.md) or
[any tool loop](how-to/custom-agent.md).

[Agent quickstart →](quickstart.md#test-an-agent){ .md-button .md-button--primary }
[Agent outcomes →](reference/agent-outcomes.md){ .md-button }

## Test an LLM pipeline

For applications that put untrusted text into their own model calls: a local
OpenAI-compatible endpoint serves your SDK client scripted, replayed or
recorded replies and captures every request. Check where untrusted text
landed, how the application handles a hostile reply, and how it handles real
replies captured earlier, all in CI with no API key.

[Pipeline tests →](how-to/pipeline-testing.md){ .md-button .md-button--primary }
[Response folders →](how-to/response-folders.md){ .md-button }

## What a result means

A failing chatbot check found a problem in a response. A passing one found
none of the patterns it looks for; the graders' measured accuracy is on the
[grading accuracy](reference/grading-accuracy.md) page.

An agent attack trial fails only when the harness recorded the agent calling
the forbidden tool or sending the canary, including calls your own code
blocked. It passes as `resisted` only when the harness saw the injected
content delivered and recorded nothing forbidden. Missing evidence is
`inconclusive`, and a model that can't call tools is `unsupported`. Whether
the task succeeded is reported by your agent and tracked separately.

A green run means these cases passed, not that your system is secure: the
attacks are fixed and simple next to an attacker who adapts to your bot. Use
the suite as a regression gate in CI, alongside red-team testing. The
[coverage matrix](about/coverage.md) lists what is and isn't tested.

## Where to go next

- [Run in CI](how-to/ci-integration.md), with per-run request counts.
- [Run fully local](how-to/local-models.md) with Ollama, vLLM or llama.cpp.
- [Test application boundaries](how-to/application-packs.md): retrieval,
  memory, tenant and role separation, and approvals.
- [API reference](reference/api.md) and
  [stability policy](reference/stability.md).
- For coding agents: [llms.txt](https://pytest-wardenbot.wardenbot.ai/llms.txt)
  and [llms-full.txt](https://pytest-wardenbot.wardenbot.ai/llms-full.txt).

## How it relates to other tools

- **Promptfoo** runs red-team and evaluation suites from a CLI, including MCP
  security testing. pytest-wardenbot runs inside the pytest suite and CI you
  already have, and grades agents on recorded actions rather than final text.
- **RAMPART** also brings security testing to pytest, built on PyRIT's attack
  generation. pytest-wardenbot keeps a small core install and its own
  controlled harness, with versioned scenarios, required coverage and
  portable evidence.
- **DeepEval** and **Inspect AI** provide evaluation metrics and agent
  evaluation infrastructure. pytest-wardenbot focuses on security regressions
  with explicit outcomes, and uses DeepEval for its optional semantic checks.
- **Garak** and **PyRIT** are broad attack and research toolkits.
- **MCP scanners** inspect servers and tool definitions; pytest-wardenbot
  tests how your agent behaves when what those servers send is hostile.

pytest-wardenbot is in Beta. Share feedback in
[GitHub Discussions](https://github.com/wardenbot-ai/pytest-wardenbot/discussions);
the [changelog](changelog.md) lists what changed.

## Powered by

[WardenBot AI](https://wardenbot.ai) runs continuous security monitoring for
AI chatbots and agents. This plugin is the free, open-source slice of that
work: the same kinds of checks, in your own CI.
[Tell us about your setup](https://wardenbot.ai/intake/) if you want them run
continuously against your deployed systems.
