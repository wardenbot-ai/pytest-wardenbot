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

- Runs on every push to `main` and every PR, with read-only repository access.
- Installs Python 3.12 and an exact pytest-wardenbot version; every action is
  pinned to a commit SHA. Bump both when you choose to (Dependabot can).
- Runs the shipped checks in `test_my_bot.py` against your real chatbot.
- Posts a Slack message on failure (if `SLACK_WEBHOOK_URL` is set), passing
  workflow values as environment variables rather than shell code.

## Cost

The deterministic checks call no judge model, but they send about 35 requests
to your chatbot per run (more with each business fact you add), which your
model provider may bill. With LLM-judge tests from the `[judge]` extra, add
about $0.003 per judge case with Claude Haiku 4.5, or nothing with a local
judge model.

To keep pull requests cheap, run the judge tests on a nightly schedule and the
deterministic checks on every pull request. See the
[CI guide](https://pytest-wardenbot.wardenbot.ai/how-to/ci-integration/) for
per-run request counts and an agent-suite job.
