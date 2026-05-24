# Example: GitHub Actions workflow

Run pytest-wardenbot on every push to `main` and every PR. Sends a Slack alert
when a wardenbot test fails (optional).

## Use

1. Copy [`wardenbot.yml`](./wardenbot.yml) into your repo at
   `.github/workflows/wardenbot.yml`.
2. Add secrets to your repo settings:
   - `CHATBOT_URL` — your chatbot endpoint
   - `CHATBOT_TOKEN` — auth token (if your bot needs one)
   - (optional) `ANTHROPIC_API_KEY` — only if you've added LLM-judge tests
   - (optional) `SLACK_WEBHOOK_URL` — only if you want failure alerts
3. Make sure your repo has a `conftest.py` and `test_my_bot.py` at the root
   (run `pytest --wardenbot-quickstart` to generate them).
4. Push.

## What this does

- Runs on every push to `main` and every PR.
- Installs Python 3.12 + pytest-wardenbot.
- Executes the shipped tests against your real chatbot.
- Posts a Slack message on failure (if `SLACK_WEBHOOK_URL` is set).

## Cost

The deterministic tests are free (no LLM API calls). If you've added LLM-judge
tests via the `[judge]` extra, expect ~$0.02 per workflow run against Anthropic
Haiku 4.5.

For frequent runs, consider:

- Marking the LLM-judge tests with `@pytest.mark.slow` and gating them behind a
  manual `workflow_dispatch` trigger.
- Running only on PR (not every push to main).
- Using the deterministic-only subset on every push, with a nightly cron for
  the full suite.
