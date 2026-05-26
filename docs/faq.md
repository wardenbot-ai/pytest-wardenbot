# FAQ

## Does this actually run against my real chatbot?

Yes. The deterministic tests open an HTTP session (or call your custom
adapter) and send real prompts to your real bot. If you don't want that
in CI, you can use the included mock adapters in your own tests instead.

## Will running this cost me money?

The deterministic tests are free (they don't call any LLM). The optional
LLM-judge tests cost roughly `$0.02` per full suite run against Anthropic
Haiku 4.5. See [Enable LLM-judge tests](how-to/llm-judge-setup.md) for
the cost breakdown.

## Does it require Anthropic / OpenAI API keys?

Only for the optional LLM-judge tests. The deterministic suite has zero
API-key requirements.

## My chatbot is general-purpose, not domain-scoped. Will the off-topic test fail?

Yes — by design. The off-topic test assumes a scoped customer-service /
support bot. If your bot is intentionally general-purpose, skip the file:

```bash
pytest --ignore=test_off_topic.py
```

Or remove the import from your generated `test_my_bot.py`.

## What about agentic AI (tool calls / function calls)?

v0.1 doesn't include tool-call-specific tests. v0.2 will add a runner
backed by Microsoft RAMPART for Cross-Prompt Injection Attack (XPIA)
testing against agents that use tools. Track progress in [GitHub Issues](https://github.com/pardamike/pytest-wardenbot/issues).

## My bot is behind a login. How do I test it?

Three options:

1. Provide a test user's session token via `CHATBOT_TOKEN` and put it in
   the `Authorization` header (the bundled `HTTPChatbotAdapter` does this
   pattern out of the box).
2. Write a custom adapter that performs the login flow first and then
   uses the resulting session cookie.
3. Have your platform team mint a permanent service-account token
   specifically for wardenbot testing.

## Can I test a Slack / Discord / Teams bot?

You'd need a custom adapter. v0.1 doesn't ship one. The pattern: have
your test bot send DMs to a wardenbot bot account, and the adapter reads
the response. v0.2 will add bundled Slack and Discord adapters.

## What model does the LLM judge use?

Anthropic Haiku 4.5 by default. Override via the `model_name` parameter
in `judge_response` / `assert_judge_passes`, or write a custom adapter.

## How reliable is the LLM judge?

Per published research, single LLM judges agree with human raters about
80% of the time on safety/quality scoring. Treat results as triage
signal, not absolute pass/fail. v0.2 adds ensemble mode (multiple judges
vote) for safety-critical metrics.

## My CI keeps failing flakily on the same test.

For LLM-judge tests, set the chatbot's temperature to 0 (or as low as
your model allows) to reduce variance. If a *deterministic* test fails
intermittently, that's usually real model drift, not flake. Investigate
before reaching for `--reruns`.

## Can I run this in parallel?

Yes, `pytest-xdist` works:

```bash
pip install pytest-xdist
pytest -n auto
```

Note that running many tests in parallel against the same chatbot
endpoint can hit rate limits on the chatbot side, which surfaces as
test failures. Tune `-n` accordingly.

## Why not just ship as a CLI tool?

A pytest plugin integrates with everything `pytest` does — fixtures,
parametrize, markers, your existing CI, your existing test runner,
your existing report format. A standalone CLI would reinvent all of
that. You probably already have pytest in your stack.

## Does this work with hosted chatbot platforms like Voiceflow / Intercom Fin?

The HTTP adapter works against any chatbot that has a JSON API endpoint.
For hosted platforms whose chatbots only have a web widget (no API), see
the managed [WardenBot AI](https://wardenbot.ai) service — it uses a real
browser to drive the widget, which is outside the OSS plugin's scope.

## How do I get help?

- [Open an issue](https://github.com/pardamike/pytest-wardenbot/issues/new/choose)
- Check the [examples](https://github.com/pardamike/pytest-wardenbot/tree/main/examples)
- For security reports, see [SECURITY.md](https://github.com/pardamike/pytest-wardenbot/blob/main/SECURITY.md)
