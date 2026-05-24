# CI integration

Run `pytest-wardenbot` on every push so chatbot regressions get caught
before customers see them.

## GitHub Actions

Drop this into `.github/workflows/wardenbot.yml`:

```yaml
name: wardenbot

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch: {}

jobs:
  wardenbot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install pytest-wardenbot
      - name: Run tests
        env:
          CHATBOT_URL: ${{ secrets.CHATBOT_URL }}
          CHATBOT_TOKEN: ${{ secrets.CHATBOT_TOKEN }}
        run: pytest -v --tb=short
```

Add `CHATBOT_URL` (and `CHATBOT_TOKEN` if your bot needs auth) to repo
secrets under Settings → Secrets and variables → Actions.

Full example with optional Slack notification on failure:
[`examples/github_actions/wardenbot.yml`](https://github.com/pardamike/pytest-wardenbot/tree/main/examples/github_actions)

## GitLab CI

```yaml
wardenbot:
  image: python:3.12
  script:
    - pip install pytest-wardenbot
    - pytest -v --tb=short
  variables:
    CHATBOT_URL: $CHATBOT_URL
    CHATBOT_TOKEN: $CHATBOT_TOKEN
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

## CircleCI

```yaml
version: 2.1

jobs:
  wardenbot:
    docker:
      - image: cimg/python:3.12
    steps:
      - checkout
      - run:
          name: Install
          command: pip install pytest-wardenbot
      - run:
          name: Run tests
          command: pytest -v --tb=short

workflows:
  test:
    jobs:
      - wardenbot:
          context:
            - chatbot-secrets   # exposes CHATBOT_URL + CHATBOT_TOKEN
```

## Cost-aware scheduling

Deterministic tests are free (no LLM API spend). If you add LLM-judge tests
via the `[judge]` extra, each suite run costs roughly `$0.02`. For
frequent runs, you have options:

- **Tag judge tests and gate them.** Mark them with `@pytest.mark.slow`
  and only run them on `main` (not every PR).
- **Run deterministic on every push, judge on nightly cron.**
- **Skip judge tests entirely** if your suite of deterministic tests is
  comprehensive enough for your needs.

Example: split workflow that runs deterministic on PR, judge on nightly:

```yaml
on:
  pull_request: {}        # deterministic only
  schedule:
    - cron: "0 6 * * *"   # nightly with judge

jobs:
  wardenbot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install (with judge on schedule only)
        run: |
          if [ "${{ github.event_name }}" = "schedule" ]; then
            pip install 'pytest-wardenbot[judge]'
          else
            pip install pytest-wardenbot
          fi
      - name: Run tests
        env:
          CHATBOT_URL: ${{ secrets.CHATBOT_URL }}
          CHATBOT_TOKEN: ${{ secrets.CHATBOT_TOKEN }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: pytest -v --tb=short
```

## Handling intermittent failures

LLM responses are stochastic. A test that passes 99/100 times will
occasionally fail in CI. Two mitigations:

- **Set `temperature=0` in your chatbot** (or as low as your model allows).
  Reduces variance.
- **Use `pytest-rerunfailures`** to retry flaky tests:

    ```bash
    pip install pytest-rerunfailures
    pytest --reruns 2 --reruns-delay 5
    ```

If a deterministic test fails intermittently, that's likely real model
drift, not flake. Investigate before reaching for `--reruns`.
