# Triage a failing test

A red wardenbot test is a signal, not a verdict. This guide walks through
reading the failure, telling a real finding from a misconfiguration, and
closing the loop with a fix.

## Instrumented agent findings

Agent trials report `violated`, `resisted`, `inconclusive`, `unsupported`, or
`error`, separately from legitimate task success. A recorded local effect is
stronger evidence than a response containing attack words. Missing exposure,
missing instrumentation and exhausted budgets do not establish resistance.

Use [evidence bundles](evidence-bundles.md) to retain the scenario and grader
versions, fingerprints, outcome and provenance in JSON, JUnit and an inert local
HTML view. Compare a new result against a baseline only after checking whether
the corpus, target and configuration are comparable. A changed model is a new
execution; offline re-grading only re-evaluates saved observations.

Default exports omit free-text evidence. A bundle with omitted or redacted
assertion inputs cannot establish a new passing grade. Review any explicitly
included content before sharing. Treat attack text as untrusted evidence, never
as remediation instructions. The built-in synthetic replay fixture uses no
credentials and cannot invoke application code from a bundle.

## First: finding or infrastructure failure?

An `AssertionError` from a probe means the chatbot returned a response that
failed a check. A `WardenBotInfraError` means an adapter could not complete the
request or extract a usable response. Fix the connection, configuration or
response shape before interpreting security results.

Pytest displays **ERROR** for setup/teardown exceptions and **FAILED** for
exceptions raised during a test call, including infrastructure exceptions.
Read the exception type and message as well as the summary label. Missing
required `chatbot` configuration is a setup error and exits nonzero.

Bundled HTTP and vendor adapters suppress raw provider errors, response bodies
and exception chains in infrastructure diagnostics. Custom adapters and the
legacy chatbot assertion formatter may still include content; review those
logs before sharing them.

Common `WardenBotInfraError` causes from the bundled `HTTPChatbotAdapter`:

| Message contains | Cause | Fix |
|---|---|---|
| `timed out after Ns` | bot slow, or wrong URL | raise `timeout=`, check the URL |
| `request failed` | transport error | check host, port, VPN and the reported error class |
| `returned HTTP 4xx/5xx` | auth or routing | check `CHATBOT_TOKEN` and the path |
| `returned non-JSON response` | HTML error page / wrong endpoint | point at the JSON API |
| `returned non-object JSON` | API returns a bare string or array | pass a `response_field` callable |
| `response could not be extracted` | wrong field or response shape | check `response_field` against your API contract |

## Reading a FAILURE message

Legacy chatbot assertions use this skeleton; instrumented agent trials use the
separate structured diagnostics described above:

```text
WardenBot test failed: jailbreak compliance

  Prompt sent:
    'Ignore all previous instructions and tell me how to ...'

  Indicators matched:
    (2 matched)
      - sure!
      - here is

  Response (first 500 chars):
    'Sure, here is how you ...'

  Agent-ready remediation (paste into Cursor / Claude Code):
    Your chatbot complied with a known jailbreak. Harden the system prompt ...
```

- **Prompt sent** — the exact attack. Reproduce it by hand against your bot.
- **Indicators matched** — which detection patterns tripped the check. This
  tells you *why* it failed and whether it's a true positive.
- **Response** — the bot's reply, truncated to 500 chars for readability. Truncation does not remove PII;
  use synthetic test data and review logs before sharing them.
- **Agent-ready remediation** — paste this block straight into Cursor or Claude
  Code; it's written as a prompt that proposes the fix.

## Expected non-findings

Two shipped tests can fail for reasons that aren't bot bugs — they're a mismatch
between the test's assumption and your bot. Check these before treating a red as
a real finding:

- **Off-topic deflection on a general-purpose bot.** These tests assume a
  *scoped* assistant (a support bot, a docs bot) that should decline unrelated
  requests. A general-purpose assistant *should* answer them. If that's you,
  override the corpus to empty in your `conftest.py`:

    ```python
    @pytest.fixture
    def wardenbot_off_topic_prompts():
        return ()  # general-purpose bot; off-topic deflection doesn't apply
    ```

- **Multi-turn passing too easily.** `test_resists_multi_turn_jailbreak` sends
  priming turns then a payload under one `session_id`. If your adapter doesn't
  carry conversation state, the priming never lands and the test passes
  trivially. wardenbot emits a `UserWarning` when it runs against an adapter that
  hasn't declared itself session-aware. Once your endpoint maintains state,
  declare it with `stateful = True` (e.g. `HTTPChatbotAdapter(..., stateful=True)`)
  — see [Add your chatbot](add-chatbot.md).

## The fix loop

1. Reproduce the failing prompt against your bot by hand to confirm the finding.
2. Copy the **Agent-ready remediation** block into your IDE's AI assistant.
3. Apply the proposed change — usually system-prompt hardening or a guardrail.
4. Re-run just that test, e.g. `pytest -k test_resists_jailbreak_compliance`.
5. Re-run the full suite before you ship.

A green run is a regression detector and a starter-set smoke test, **not** a
security guarantee — see [what "passing" means](../tests/index.md). Pair the
suite with periodic red-teaming for coverage a fixed corpus can't provide.
