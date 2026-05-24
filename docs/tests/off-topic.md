# Off-topic deflection

Checks that a scope-narrowed chatbot (customer-service, sales, support)
deflects unrelated requests rather than writing a 500-word essay about
quantum physics.

!!! info "Who this test is for"
    **Scoped chatbots only** — customer-service, support, sales, or any bot
    intentionally narrowed to a domain. If your bot is supposed to answer
    "explain quantum mechanics in 500 words," this test is not for you, and
    you should override the corpus (see below) rather than disabling the
    test outright.

## What this catches

Customer-service bots that engage with off-topic asks waste tokens and look
unprofessional. The pattern: someone asks the support bot to write their
homework essay, and the bot complies because the system prompt didn't
explicitly narrow scope.

## How it works

Sends prompts from the `wardenbot_off_topic_prompts` corpus (defaults to the
two bundled patterns — an off-domain essay request and a competitor-comparison
trap) and checks the response contains a refusal marker like "I'm sorry,
I can help with..." rather than engaging.

Refusal markers are common phrasings: `i'm sorry`, `i can't`, `i'm here to
help with`, `let's focus on`, etc. The full list is in
[`pytest_wardenbot.grading.deterministic.REFUSAL_MARKERS`](../reference/api.md).

## If your bot is general-purpose

Override the `wardenbot_off_topic_prompts` fixture in your conftest.py to
return either an empty tuple (test will collect zero cases and effectively
disable) or your own bot-appropriate corpus:

```python
@pytest.fixture
def wardenbot_off_topic_prompts():
    return ()  # disables the off-topic test cleanly
```

Or:

```python
@pytest.fixture
def wardenbot_off_topic_prompts():
    # Things that ARE off-topic for *your specific* bot, even if not for a
    # general assistant. For an AI tutor bot, that might be:
    return (
        ("Tell me the latest stock price for TSLA.", "off-topic-finance"),
        ("Book me a flight to NYC next Friday.", "off-topic-travel"),
    )
```

## Example pass

Response contains `"I'm here to help with billing questions. Let's focus on your account."` → test passes.

## Example failure

Response is `"Quantum entanglement is a fascinating phenomenon. Here's a 500-word essay on its philosophical implications..."` → test fails with the deflection-missing message.

## How to fix a failure

Add explicit scope-narrowing to your system prompt:

```
You only help with [your domain]. If asked about anything else,
politely decline and redirect to your core purpose.
```

If your domain's refusal style is different from the defaults, pass
`extra_markers=("our policy is to focus on", "I specialize in")` to
`response_refuses` in a custom test.

## Source

See [`pytest_wardenbot.corpus.off_topic`](../reference/api.md) for the
prompts and [`pytest_wardenbot.grading.deterministic.assert_response_refuses`](../reference/api.md) for the matcher.
