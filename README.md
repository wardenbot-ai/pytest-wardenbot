# pytest-wardenbot

[![CI](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/ci.yml/badge.svg)](https://github.com/wardenbot-ai/pytest-wardenbot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/wardenbot-ai/pytest-wardenbot/branch/main/graph/badge.svg)](https://codecov.io/gh/wardenbot-ai/pytest-wardenbot)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/wardenbot-ai/pytest-wardenbot/badge)](https://scorecard.dev/viewer/?uri=github.com/wardenbot-ai/pytest-wardenbot)
[![Python versions](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://pypi.org/project/pytest-wardenbot/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/wardenbot-ai/pytest-wardenbot/blob/main/LICENSE.md)

Pytest security tests for chatbots and tool-using agents: prompt injection,
system-prompt leaks, and agents acting on instructions hidden in tool results,
MCP resources and prompts. Agent results come from what a controlled harness
recorded the agent doing, not from what the agent says. Everything can run on
your machine, including against Ollama, vLLM or llama.cpp models with no API
key.

It tests **your chatbot or agent, not your MCP server**. To scan MCP servers
and tool definitions themselves, use a scanner such as
[Snyk Agent Scan](https://github.com/snyk/agent-scan) or
[Cisco's MCP Scanner](https://github.com/cisco-ai-defense/mcp-scanner).

📖 [Documentation](https://pytest-wardenbot.wardenbot.ai/) ·
[llms.txt](https://pytest-wardenbot.wardenbot.ai/llms.txt) for coding agents ·
**Beta (0.6):** public APIs change only under the
[stability policy](https://pytest-wardenbot.wardenbot.ai/reference/stability/).

## Quickstart: chatbot

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart                  # writes conftest.py and test_my_bot.py
export CHATBOT_URL=https://your-bot.example.com/chat
pytest                                         # 29 checks, about 35 requests to your bot
```

The generated `conftest.py` posts `{"message": "..."}` and reads
`{"response": "..."}`; change the two field names there if your bot differs.
For OpenAI, Anthropic, LangChain and other clients, see
[Add your chatbot](https://pytest-wardenbot.wardenbot.ai/how-to/add-chatbot/).

## Quickstart: agent

```bash
pip install "pytest-wardenbot[mcp,openai]"
pytest --wardenbot-quickstart=agent            # writes conftest.py and test_my_agent.py
export OPENAI_API_KEY=sk-...                   # or: export AGENT_LOCAL=ollama AGENT_MODEL=qwen2.5:7b
pytest --wardenbot-agent-required              # 8 scenarios, each with a baseline and an attack
```

The generated `conftest.py` contains a complete tool-calling agent, so the
first run tests a real model end to end. Then replace it with your own agent:

| Your agent | Connect it with |
| --- | --- |
| LangGraph | [`LangGraphAgentTarget`](https://pytest-wardenbot.wardenbot.ai/how-to/langgraph-agent/) (`[langgraph]`) |
| Claude Agent SDK | [`ClaudeAgentTarget`](https://pytest-wardenbot.wardenbot.ai/how-to/claude-agent/) (`[claude-agent]`), isolated from your machine |
| OpenAI Agents SDK | [Recipe](https://pytest-wardenbot.wardenbot.ai/how-to/openai-agents/) |
| Any other tool loop | [40-line custom target](https://pytest-wardenbot.wardenbot.ai/how-to/custom-agent/) with `TrialTools` |

## What a result means

**Chatbot suite.** A failing check found a problem in a response: the bot
followed an injected instruction, complied with a request it should have
refused, or leaked its system prompt (planting a
[canary token](https://pytest-wardenbot.wardenbot.ai/how-to/canary-token/)
makes leak checks much stronger). A passing check found none of the patterns
it looks for. The graders are measured on
[744 labeled responses](https://pytest-wardenbot.wardenbot.ai/reference/grading-accuracy/):
none of the 492 well-behaved replies fail, and the page lists the known misses
and how the graders did on replies they had never seen.

**Agent suite.** An attack trial fails only when the harness recorded the
agent calling the forbidden tool or sending the canary, including calls your
own code blocked. It passes as `resisted` only when the harness saw the
injected content delivered and recorded nothing forbidden. Missing evidence
is `inconclusive`, and a model that can't call tools is `unsupported`, never
`resisted`. Each attack has a benign baseline; whether the task succeeded is
reported by your agent and tracked separately. See
[agent outcomes](https://pytest-wardenbot.wardenbot.ai/reference/agent-outcomes/).

A green run means these cases passed, not that your system is secure. The
attacks are fixed and simple next to a motivated attacker who adapts to your
bot. Use the suite as a regression gate in CI, alongside red-team testing.

## Chatbot suite

| Category | Checks | Grading |
|---|---|---|
| Prompt injection / jailbreak resistance | 5 prompts × 2 checks | deterministic |
| System-prompt elicitation | 3 | deterministic, canary-first |
| Refusal bypass (roleplay, pretext, hypothetical) | 3 | deterministic |
| Off-topic deflection (for scoped bots) | 2 | deterministic |
| Indirect (cross-prompt) injection | 4 | deterministic |
| Encoded payloads (Base64, ROT13, leet, hex) | 4 | deterministic |
| Multi-turn jailbreak (needs a session-aware adapter) | 3 | deterministic |
| Business facts (your prices, hours, policies) | one per fact | deterministic |
| Semantic checks (`[judge]` extra) | one per case | LLM judge, hosted or local |

No judge model is involved unless you add judge cases. When a check fails, the
message includes a Markdown remediation brief you can paste into Cursor or
Claude Code; the bot's reply is fenced as untrusted text.

Adapters: HTTP, OpenAI Responses and Chat Completions, Anthropic Messages,
LangChain Runnables, Ollama/vLLM/llama.cpp presets, or any object with
`send_message` and `reset_session`.

## Agent suite

- **Eight versioned MCP scenarios** inject instructions through tool results,
  tool descriptions, resources and prompts, over real local MCP transports.
  Each checks a forbidden tool call or a synthetic canary, with a benign
  baseline.
- **Required mode** (`--wardenbot-agent-required`) fails the run if any
  selected case is skipped, deselected, unsupported or lacks evidence, also
  under pytest-xdist.
- **Application packs** (opt-in) cover poisoned retrieval, cross-session
  memory, tenant and role separation, and approval before write, through
  hooks into your own application.
- **Bounded campaigns** share call and turn budgets across repeated trials;
  **portable evidence** saves versioned results as JSON, JUnit or
  self-contained HTML that can be re-graded later.
- **Fully local:** the [local presets](https://pytest-wardenbot.wardenbot.ai/how-to/local-models/)
  check that a model can call tools first, and a CI test proves local runs
  make no outside network connections.

## Install extras

```bash
pip install "pytest-wardenbot[mcp]"          # controlled MCP harness for the agent suite
pip install "pytest-wardenbot[langgraph]"    # LangGraph agent target
pip install "pytest-wardenbot[claude-agent]" # Claude Agent SDK agent target
pip install "pytest-wardenbot[openai]"       # OpenAI adapters (sync and async)
pip install "pytest-wardenbot[anthropic]"    # Anthropic adapter (sync and async)
pip install "pytest-wardenbot[langchain]"    # LangChain Runnable adapter
pip install "pytest-wardenbot[judge]"        # DeepEval semantic checks
pip install "pytest-wardenbot[async]"        # pytest-asyncio for parallel probes
```

Python 3.11–3.14, pytest 8.1.1 or later. The package ships type hints
(`py.typed`). Releases are published from CI with PyPI attestations, an SBOM
and a maintainer approval step; see [SECURITY.md](https://github.com/wardenbot-ai/pytest-wardenbot/blob/main/SECURITY.md).

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
- **MCP scanners** such as Snyk Agent Scan and Cisco's MCP Scanner inspect
  servers and tool definitions; pytest-wardenbot tests how your agent behaves
  when what those servers send is hostile.

Questions and feedback: [GitHub Discussions](https://github.com/wardenbot-ai/pytest-wardenbot/discussions).
Bugs: [GitHub Issues](https://github.com/wardenbot-ai/pytest-wardenbot/issues).

## License

Apache 2.0. See [LICENSE.md](https://github.com/wardenbot-ai/pytest-wardenbot/blob/main/LICENSE.md).

## Powered by

[WardenBot AI](https://wardenbot.ai) runs continuous security monitoring for
AI chatbots and agents. This plugin is the free, open-source slice of that
work: the same kinds of checks, in your own CI.
[Tell us about your setup](https://wardenbot.ai/intake/) if you want them run
continuously against your deployed systems.
