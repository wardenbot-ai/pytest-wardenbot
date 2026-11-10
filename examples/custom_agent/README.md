# Custom agent target

`conftest.py` is a complete agent target for the packaged agent suite: an
OpenAI-compatible tool loop over the controlled MCP harness tools, using
`TrialTools` for the bookkeeping. The agent class is about 40 lines.

```bash
python -m pip install "pytest-wardenbot[mcp,openai]"
export OPENAI_API_KEY=...
pytest --pyargs pytest_wardenbot.agent_tests
```

Set `AGENT_MODEL` to choose a model and `AGENT_BASE_URL` for an
OpenAI-compatible local server. The walkthrough is in the docs:
[Connect your own agent](https://pytest-wardenbot.wardenbot.ai/how-to/custom-agent/).

The repository runs this file offline in CI against a scripted model
(`tests/test_custom_agent_example.py`): 16 passing cases with a resistant
model, and 8 confirmed violations with a vulnerable one.
