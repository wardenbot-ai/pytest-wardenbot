# OpenAI Agents SDK target

`conftest.py` runs an agent built on the OpenAI Agents SDK through the
packaged agent suite: the harness tools become `FunctionTool`s, `TrialTools`
does the bookkeeping, run hooks enforce turns and report requested tool calls,
and tracing is disabled.

```bash
python -m pip install "pytest-wardenbot[mcp]" openai-agents
export OPENAI_API_KEY=...
pytest --pyargs pytest_wardenbot.agent_tests
```

Walkthrough: [Test an OpenAI Agents SDK agent](https://pytest-wardenbot.wardenbot.ai/how-to/openai-agents/).
The repository runs this file offline in CI (`tests/test_openai_agents_example.py`).
