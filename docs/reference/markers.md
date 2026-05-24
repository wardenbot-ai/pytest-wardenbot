# Pytest markers

`pytest-wardenbot` registers four pytest markers so they pass under
`--strict-markers`. Use them to filter, group, or skip tests.

## `@pytest.mark.wardenbot`

Identifies a test as provided by (or stylistically aligned with)
`pytest-wardenbot`. All shipped tests carry this marker. Apply it to
your own custom tests if you want them to be selectable alongside the
shipped suite.

```python
import pytest

@pytest.mark.wardenbot
def test_my_custom_check(chatbot):
    ...
```

Select only wardenbot tests:

```bash
pytest -m wardenbot
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
these four so they always pass `--strict-markers`, even before any test
is collected.

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
