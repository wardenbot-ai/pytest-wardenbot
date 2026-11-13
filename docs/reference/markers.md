# Pytest markers

`pytest-wardenbot` registers its pytest markers so they pass under
`--strict-markers`. Use them to filter, group, or skip tests.

## `@pytest.mark.wardenbot`

Identifies a test as provided by (or stylistically aligned with)
`pytest-wardenbot`. All shipped tests carry this marker. Apply it to
your own custom tests if you want them to be selectable alongside the
shipped suite.

```python
import pytest


@pytest.mark.wardenbot
def test_my_custom_check(chatbot): ...
```

Select only wardenbot tests:

```bash
pytest -m wardenbot
```

## `@pytest.mark.wardenbot_model`

Runs a test inside a `model_endpoint` block through the `wardenbot_model`
fixture, with the marker's keyword arguments: `script=`, `mutate=` and `case=`.
The case defaults to the test's node id. The fixture yields the block, whose
`requests` are the requests the application sent during the test. See
[Test an LLM pipeline without a live model](../how-to/pipeline-testing.md).

```python
import pytest


@pytest.mark.wardenbot_model(script={"ratings": []})
def test_page_text_stays_fenced(wardenbot_model):
    rate_sources(SOURCES)
    assert wardenbot_model.requests
```

## Severity markers

| Marker | When to use |
|---|---|
| `@pytest.mark.severity_high` | Behavior that could cause customer harm if undetected (jailbreak compliance, system-prompt leak, refusal-bypass, factual hallucination of business-critical facts) |
| `@pytest.mark.severity_medium` | Behavior that's customer-noticeable but lower-stakes (off-topic engagement, brand voice drift, refusal quality) |
| `@pytest.mark.severity_low` | Cosmetic / DX issues |

All shipped tests are tagged with `severity_high` or `severity_medium`. Run
only the high-severity subset:

```bash
pytest -m severity_high
```

Combine with `wardenbot`:

```bash
pytest -m "wardenbot and severity_high"
```

## Why register markers explicitly?

Pytest's `--strict-markers` mode (which we enable by default in
`pyproject.toml`) errors on unregistered markers. The plugin registers
these markers so they always pass `--strict-markers`, even before any test
is collected.

## Agent scenario markers

The separate `pytest_wardenbot.agent_tests` suite uses:

| Marker | Metadata |
|---|---|
| `wardenbot_agent` | `surface`, `assertion`, `scenario_id`, `version`, `phase` (`baseline` or `attack`), `pack` |
| `wardenbot_agent_capability` | Required capability name such as `isolated_state`, `tool_results`, or `tool_calls` |

These markers accompany each generated scenario node. Pytest 8.3 and later
[support keyword matching](https://docs.pytest.org/en/stable/changelog.html#pytest-8-3-0-2024-07-20)
against string marker metadata:

```bash
pytest --pyargs pytest_wardenbot.agent_tests \
  -m "wardenbot_agent(surface='tool_result')"
```

On every supported pytest version, the explicit scenario option selects the
same scenario and both phases:

```bash
pytest --pyargs pytest_wardenbot.agent_tests \
  --wardenbot-agent-scenario=mcp.tool-result.forbidden-tool@2
```

For required coverage, define the expected scenarios with
`--wardenbot-agent-scenario` or `--wardenbot-agent-pack` and add `--wardenbot-agent-required`. Excluding
required nodes with a marker expression, skip, or xfail leaves coverage
incomplete and returns a nonzero exit. See the agent scenarios how-to for
fixture setup and outcome semantics.

Application groups are opt-in: `--wardenbot-agent-pack=application` selects
retrieval, memory, identity and approval checks; a group such as
`--wardenbot-agent-pack=memory` selects only that pack. On pytest 8.3+, use
`-m "wardenbot_agent(pack='memory')"` to filter already selected nodes.
Filtering never adds a pack that was not selected. The default remains MCP.

## Adding your own markers

If you want to extend the tagging scheme (e.g., `@pytest.mark.requires_auth`),
register in your project's `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "requires_auth: test needs CHATBOT_TOKEN to be set",
]
```

Wardenbot's markers stay registered automatically.
