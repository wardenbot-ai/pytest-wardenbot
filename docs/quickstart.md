---
description: Install the plugin, point it at your chatbot or agent and get a first red-or-green result.
---

# Quickstart

Two paths, each a few minutes from `pip install` to a first result. Use
Python 3.11 or later.

## Test a chatbot

### 1. Install and generate starter files

```bash
pip install pytest-wardenbot
pytest --wardenbot-quickstart
```

This writes two files in the current directory:

- `conftest.py`: the `chatbot` fixture that points at your bot, and a
  `business_truth_fact` fixture with placeholder facts;
- `test_my_bot.py`: imports the shipped checks, so plain `pytest` runs them.

Industry templates start you with richer placeholder facts:

```bash
pytest --wardenbot-quickstart=ecommerce       # refund and shipping facts
pytest --wardenbot-quickstart=saas-support    # plan and trial facts
```

### 2. Point it at your chatbot

```bash
export CHATBOT_URL=https://your-bot.example.com/chat
export CHATBOT_TOKEN=sk-your-token              # optional, sent as a Bearer token
```

The generated fixture posts `{"message": "..."}` and reads
`{"response": "..."}`. If your bot uses other field names, change
`request_field` and `response_field` in `conftest.py`. Until `CHATBOT_URL` is
set, every check fails setup with a message saying so, rather than passing
without contacting a bot.

Not a JSON-over-HTTP bot? Install an extra and use a bundled adapter
(`[openai]`, `[anthropic]`, `[langchain]`), a
[local model preset](how-to/local-models.md), or write a small adapter; see
[Add your chatbot](how-to/add-chatbot.md).

### 3. Run

```bash
pytest
```

The first run sends about 35 requests to your bot: 29 checks, three of which
send three messages. The placeholder facts are skipped until you replace
them, so a first run can't fail on an answer you never set.

### 4. Replace the placeholder facts

Each `BusinessTruthFact` in `conftest.py` is one question your bot must answer
correctly. Edit the placeholders to your real answers:

```python
from pytest_wardenbot.business_truth import BusinessTruthFact

BusinessTruthFact(
    label="Standard plan price",
    question="How much does the Standard plan cost per month?",
    expected_answer="$49",
    match_type="substring",
    acceptable_variations=("49/mo", "forty-nine dollars"),
)
```

Each fact becomes one test, which fails with the question and the bot's
answer when the bot gets it wrong.

### 5. Read the failures

A failure says which check failed and why, then shows the bot's reply fenced
as untrusted text, and ends with a block labeled
`Agent-ready remediation (paste into Cursor / Claude Code)`. Paste that block
into your coding assistant to draft a fix, then run `pytest` again.
[Triage a failing test](how-to/triage-failures.md) explains each kind of
failure, and [plant a canary token](how-to/canary-token.md) to make the leak
checks much stronger.

## Test an agent

### 1. Install and generate starter files

```bash
pip install "pytest-wardenbot[mcp,openai]"
pytest --wardenbot-quickstart=agent
```

This writes:

- `conftest.py`: `MyAgent`, a complete tool-calling agent (an
  OpenAI-compatible chat loop over the controlled harness tools), plus the
  `agent_target`, `agent_harness` and `agent_observer` fixtures;
- `test_my_agent.py`: imports the packaged agent suite.

### 2. Choose a model

```bash
export OPENAI_API_KEY=sk-...                    # OpenAI; AGENT_MODEL defaults to gpt-4.1-mini
```

Or run fully local with [Ollama](https://ollama.com), vLLM or llama.cpp:

```bash
ollama pull qwen2.5:7b
export AGENT_LOCAL=ollama AGENT_MODEL=qwen2.5:7b
```

With a local model the agent first checks that the model can call tools. If
it can't, every case is reported as `unsupported` rather than `resisted`.

### 3. Run

```bash
pytest --wardenbot-agent-required
```

The suite runs eight versioned MCP scenarios, each twice: a benign baseline,
then the same task with an injected instruction in a tool result, tool
description, resource or prompt. A trial fails only if the harness recorded
the agent calling the forbidden tool or sending the canary. Required mode
makes a skipped, unsupported or incomplete case fail the run instead of
passing quietly.

Expect 16 trials of 2–4 model requests each. In our runs, `gpt-4.1-mini`
took 26 seconds and about a third of a cent (36 requests), and `qwen2.5:7b`
took about 70 seconds on an M3 Pro laptop. Both violated 6 of the 8 attacks.
If a case errors, run again with `--wardenbot-agent-debug` to see the
underlying error locally.

### 4. Connect your own agent

Replace `MyAgent` in `conftest.py` with your agent, built exactly as in
production but given the harness's tools instead of your real ones:

| Your agent | Connect it with |
| --- | --- |
| LangGraph | [`LangGraphAgentTarget`](how-to/langgraph-agent.md) (`[langgraph]`) |
| Claude Agent SDK | [`ClaudeAgentTarget`](how-to/claude-agent.md) (`[claude-agent]`) |
| OpenAI Agents SDK | [Recipe](how-to/openai-agents.md) |
| Any other tool loop | [Custom target with `TrialTools`](how-to/custom-agent.md) |

[Agent outcomes and reason codes](reference/agent-outcomes.md) explains every
result. A baseline that fails with "Agent took the forbidden action with no
attack present" means the agent calls that tool on its own, so attacks on it
can't be attributed to the injection.

## Next steps

- [Run in CI](how-to/ci-integration.md), with per-run request counts.
- [Enable LLM-judge tests](how-to/llm-judge-setup.md) for semantic checks
  such as brand voice and hallucination, hosted or local.
- [Test application boundaries](how-to/application-packs.md) such as
  retrieval, memory and approvals.
