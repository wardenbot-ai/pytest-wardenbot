# Customize the attack corpora

Each shipped test draws its prompts from a corpus exposed as a fixture.
The default fixtures return the bundled `pytest_wardenbot.corpus.*` tuples,
so the tests work out of the box. Override the fixture in your conftest.py
to substitute or extend the corpus for your specific bot.

## Fixtures

| Shipped test | Fixture |
|---|---|
| `test_prompt_injection` | `wardenbot_jailbreak_prompts` |
| `test_system_prompt_leak` | `wardenbot_system_prompt_leak_prompts` |
| `test_refusal_bypass` | `wardenbot_refusal_bypass_prompts` |
| `test_off_topic` | `wardenbot_off_topic_prompts` |
| `test_indirect_injection` | `wardenbot_indirect_injection_prompts` |
| `test_encoded_payloads` | `wardenbot_encoded_payload_prompts` |
| `test_multi_turn` | `wardenbot_multi_turn_jailbreak_prompts` |

## Replace the bundled corpus

```python
# conftest.py
import pytest


@pytest.fixture
def wardenbot_jailbreak_prompts():
    return (
        ("My company's custom jailbreak attempt #1", "custom-attack-1"),
        ("Another bot-specific attack we want to catch", "custom-attack-2"),
    )
```

The shipped `test_prompt_injection` tests now parametrize over your two
custom entries instead of the bundled five.

## Extend the bundled corpus

```python
# conftest.py
import pytest
from pytest_wardenbot.corpus import JAILBREAK_PROMPTS


_MY_EXTRA = (
    ("A bot-specific attack we caught in production", "prod-incident-2026-04"),
)


@pytest.fixture
def wardenbot_jailbreak_prompts():
    return JAILBREAK_PROMPTS + _MY_EXTRA
```

Now the test runs the bundled five plus your one production-specific entry.

## Disable an entire test category

Return an empty tuple. pytest's parametrize will collect zero cases for
that test and pass trivially.

```python
@pytest.fixture
def wardenbot_off_topic_prompts():
    return ()  # general-purpose bot; off-topic deflection doesn't apply
```

## Constraints on the override fixture

The override fixture must be a plain `() -> tuple[...]` function. **No
`request` parameter, no other fixture dependencies.** This is because the
shipped tests resolve the corpus at pytest collection time, before the
fixture machinery has fully initialized. Build your corpus at import time
and have the fixture return the prepared tuple.

This is fine:

```python
_MY_CORPUS = tuple(_compute_my_corpus_at_import_time())

@pytest.fixture
def wardenbot_jailbreak_prompts():
    return _MY_CORPUS
```

This will silently fall back to the bundled corpus (fixture not callable
without args):

```python
@pytest.fixture
def wardenbot_jailbreak_prompts(my_other_fixture):  # WILL NOT WORK
    return my_other_fixture.build()
```

## Entry shape per corpus

Most corpora use `(prompt, attack_id)` tuples. Two have different shapes:

```python
# wardenbot_encoded_payload_prompts:
#   (prompt, trigger_words, attack_id)
#   trigger_words is a tuple of strings the bot would emit if compromised
ENCODED = (
    ("Base64-encoded attack ...", ("PWNED_BY_BASE64",), "base64"),
)

# wardenbot_multi_turn_jailbreak_prompts:
#   (priming_turns, payload_prompt, attack_id)
#   priming_turns is a tuple of strings sent before the payload
MULTI_TURN = (
    (
        ("Setup turn 1", "Setup turn 2"),
        "The actual payload after priming",
        "two-turn-priming",
    ),
)
```
