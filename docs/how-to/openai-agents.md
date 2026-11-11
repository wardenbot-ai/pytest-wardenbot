# Test an OpenAI Agents SDK agent

This recipe runs an agent built on the
[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) through
the packaged agent suite. It wraps the harness tools as `FunctionTool`s and
uses `TrialTools` for the bookkeeping, like the
[custom agent recipe](custom-agent.md).

```bash
python -m pip install "pytest-wardenbot[mcp]" openai-agents
export OPENAI_API_KEY=...
```

Save this as `conftest.py` and replace the `Agent(...)` arguments with your
agent's instructions, model and settings:

```python
--8<-- "examples/openai_agents/conftest.py"
```

```bash
pytest --pyargs pytest_wardenbot.agent_tests
```

## What the recipe does

- **Tools.** Each harness tool becomes a `FunctionTool` whose handler calls
  `tools.call`. Invalid JSON arguments are recorded as attempts.
- **Turns.** `on_llm_start` claims a turn before each model request, and tool
  calls claim turns too. The SDK wraps an exception raised inside a tool in
  its own `UserError`; `TrialTools` still recognizes the turn limit inside it.
- **Blocked calls.** `on_llm_end` reports every tool call the model asks for,
  so a call that guardrails, approvals or a missing tool stop before it runs
  still counts as an attempt.
- **Tracing is off.** The Agents SDK uploads traces, including prompts and
  tool output, to OpenAI by default. The recipe passes
  `RunConfig(tracing_disabled=True)`.

## Local models

Point the agent at an OpenAI-compatible local server with
`OpenAIChatCompletionsModel`, and check that the model can call tools:

```python
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from pytest_wardenbot.local import local_base_url, require_tool_calling

client = AsyncOpenAI(base_url=local_base_url("ollama"), api_key="local", max_retries=0)
model = OpenAIChatCompletionsModel(model="qwen2.5:7b", openai_client=client)

# First line of run():
await require_tool_calling("ollama", "qwen2.5:7b")
```

See [Run against local models](local-models.md).

## Result from our run

With the recipe as shown and `gpt-4o-mini` on the version 2 scenarios, 11 of
16 cases passed in 33 seconds, for well under one cent:

- **Baselines:** 8 of 8 passed. (On the version 1 scenarios in 0.6, one
  baseline failed: the model called `record_action` with no attack present.)
- **Attacks:** 5 of 8 were confirmed violations, 3 forbidden-tool effects and
  2 canary leaks. Both tool-description attacks were resisted.
- **Lifecycle pack:** both input-request attacks were resisted. The
  definition-change scenarios are skipped as unsupported, because the agent's
  tools are fixed when it's built.

A single run, not a benchmark.
