# Off-topic deflection

Checks that a scope-narrowed chatbot (customer-service, sales, support)
deflects unrelated requests rather than writing a 500-word essay about
quantum physics.

## What this catches

Customer-service bots that engage with off-topic asks waste tokens and look
unprofessional. The pattern: someone asks the support bot to write their
homework essay, and the bot complies because the system prompt didn't
explicitly narrow scope.

## How it works

Sends two prompts (an off-domain essay request and a competitor-comparison
trap) and checks the response contains a refusal marker like "I'm sorry,
I can help with..." rather than engaging.

Refusal markers are common phrasings: `i'm sorry`, `i can't`, `i'm here to
help with`, `let's focus on`, etc. The full list is in
[`pytest_wardenbot.grading.deterministic.REFUSAL_MARKERS`](../reference/api.md).

## When this test will give false positives

If your chatbot is *intentionally* general-purpose (an open AI assistant,
not a scoped support bot), this test will fail because the bot will engage
with off-topic asks. That's expected; either:

- Skip the file: `pytest --ignore=...test_off_topic.py`
- Or extend `REFUSAL_MARKERS` with your bot's specific deflection phrasings.

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
