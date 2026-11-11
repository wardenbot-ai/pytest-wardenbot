# CI integration

Run pytest-wardenbot on every push so a chatbot or agent regression fails the
build before customers see it.

## What a run costs

The deterministic checks call no judge model, but every check sends real
requests to the system you test, and those may be billed by your model
provider.

| Run | Requests | Notes |
|---|---|---|
| Chatbot suite, default quickstart | 35 to your chatbot | 29 tests; the three multi-turn tests send three messages each. Each business fact you add is one more. |
| Agent suite | 16 trials, usually 2–4 model requests each | 8 scenarios, each with a baseline and an attack. The quickstart agent made 28 requests with `gpt-4.1-mini`: 21 seconds, about a fifth of a cent. A local model costs nothing. |
| LLM-judge tests (`[judge]`) | 1 judge request per case, plus 1 chatbot request | About $0.003 per case with Claude Haiku 4.5, or free with a [local judge](llm-judge-setup.md#local-judge). |

## GitHub Actions: chatbot suite

Copy this workflow to `.github/workflows/wardenbot.yml`. It expects the
`conftest.py` and `test_my_bot.py` that `pytest --wardenbot-quickstart`
generates, at the repository root.

```yaml
--8<-- "examples/github_actions/wardenbot.yml"
```

Add `CHATBOT_URL` (and `CHATBOT_TOKEN` if your bot needs auth) under
Settings → Secrets and variables → Actions. The workflow:

- pins each action to a commit SHA and the package to an exact version, so
  the build only changes when you change it (Dependabot can bump both);
- gives the job read-only repository access and doesn't persist the checkout
  token;
- passes workflow values to the Slack step as environment variables, never as
  shell code.

## GitHub Actions: agent suite

Add a job that runs the agent suite in required mode, so a skipped, deselected
or unsupported case fails the build instead of passing quietly:

```yaml
  agent-suite:
    name: Agent suite
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
        with:
          persist-credentials: false
      - uses: actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0  # v7.1.0
        with:
          python-version: "3.12"
      - run: python -m pip install "pytest-wardenbot[mcp,openai]==0.6.1"
      - name: Run the agent suite
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: python -m pytest test_my_agent.py --wardenbot-agent-required -v
```

This assumes the files from `pytest --wardenbot-quickstart=agent`, or your own
`agent_target` and `agent_observer` fixtures. Pull requests from forks don't
receive secrets, so the job fails there; restrict it with
`if: github.event.pull_request.head.repo.full_name == github.repository` if you
accept outside contributions.

## GitLab CI

```yaml
wardenbot:
  image: python:3.12
  script:
    - python -m pip install "pytest-wardenbot==0.6.1"
    - python -m pytest test_my_bot.py -v --tb=short
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

Define `CHATBOT_URL` and `CHATBOT_TOKEN` as masked CI/CD variables in the
project settings.

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
          command: python -m pip install "pytest-wardenbot==0.6.1"
      - run:
          name: Run tests
          command: python -m pytest test_my_bot.py -v --tb=short

workflows:
  test:
    jobs:
      - wardenbot:
          context:
            - chatbot-secrets   # exposes CHATBOT_URL + CHATBOT_TOKEN
```

## Run judge tests less often

To keep pull requests fast and cheap, run the deterministic checks on every
pull request and the LLM-judge tests on a schedule:

```yaml
on:
  pull_request: {}
  schedule:
    - cron: "0 6 * * *"   # nightly, with the judge tests
```

In the job, install `pytest-wardenbot[judge]` and set `ANTHROPIC_API_KEY` only
when `github.event_name == 'schedule'`, or pass a local judge with
`--wardenbot-judge-model ollama/qwen2.5:7b` on a self-hosted runner.

## When a result changes between runs

Model output varies, so a check that passes most of the time can fail now and
then. Treat that as a finding, not as noise: a model that follows an injected
instruction one time in ten will follow it in production too.

- Don't retry failed security checks automatically (for example with
  `pytest-rerunfailures`). A retry turns "sometimes violates" into a pass.
- Lower the variance where you control it: set `temperature=0` in your
  chatbot or agent if the model allows it.
- To measure how often something happens, run repeated trials with
  [bounded campaigns](agent-campaigns.md) and report the rate.
- [Triage a failing test](triage-failures.md) explains how to read each
  failure.
