---
description: Every mode, setting, environment variable and command-line option of the local model endpoint.
---

# Model endpoint reference

The endpoint (`pytest_wardenbot.model`) is a local OpenAI-compatible HTTP
server. It serves `POST /v1/responses` (with streaming), `POST
/v1/chat/completions` (with streaming) and `GET /v1/models`, one per process.
Guides: [Test an LLM pipeline without a live model](../how-to/pipeline-testing.md),
[Response folders](../how-to/response-folders.md),
[Use it with Django's test runner](../how-to/django.md). Every name is in the
[API reference](api.md#model-endpoint-for-pipeline-tests).

## Modes

| Mode | Cases without `script=` | Calls the real API | Allowed in CI |
|---|---|---|---|
| `off` | No endpoint; `install()` changes nothing, and `script=` fails | no | yes |
| `scripted` | Fail: every case must pass `script=` | never | yes |
| `replay` | Served from the response folder; a miss fails | never | yes |
| `override` | Served from the folder; a miss goes to the real API, unsaved | on a miss | no |
| `record` | Sent to the real API; each reply written to the folder | always | no |
| `live` | Sent to the real API; nothing saved | always | no |

A case that passes `script=` is scripted in every mode except `off`, and is
never recorded. `mutate=` applies to whatever reply a case gets, and a mutated
reply is never recorded.

The mode is `off` until something configures the endpoint. Once a config file
or an explicit `install()` does, it defaults to `replay`. "Not allowed in CI"
means the mode refuses to start when `CI` is set to a true value, or a CI
service's own variable is present (Jenkins, Azure Pipelines, TeamCity, AWS
CodeBuild, Buildkite, GitHub Actions, GitLab CI).

## Where settings come from

From highest precedence to lowest:

1. the pytest options `--wardenbot-model-mode` and `--wardenbot-responses-dir`;
2. the environment variables `WARDENBOT_MODEL_MODE` and `WARDENBOT_RESPONSES_DIR`;
3. the arguments to `install(mode=..., responses_dir=...)`;
4. the config file.

The config file is the file `WARDENBOT_CONFIG` names, else the nearest
`wardenbot.toml` (`[model]` table) or `pyproject.toml` with a
`[tool.wardenbot.model]` table, searched upward from pytest's rootdir (or the
working directory) and no further than the project root. Relative paths
resolve against the file.

| Setting | What it does |
|---|---|
| `mode` | One of the modes above |
| `responses_dir` | The response folder |
| `guard_hosts` | Extra hosts for the egress guard: `host`, `host:port`, or a URL |
| `ignore_fields` | Request fields left out of the request hash: top-level names or dotted paths |
| `normalizers` | `"package.module:function"` callables applied to every string before hashing |

## Environment variables

| Variable | Set by | Meaning |
|---|---|---|
| `WARDENBOT_MODEL_MODE` | you | The mode |
| `WARDENBOT_RESPONSES_DIR` | you | The response folder |
| `WARDENBOT_CONFIG` | you | The config file to read |
| `WARDENBOT_UPSTREAM_BASE_URL` | you | The real API for `override`, `record` and `live` |
| `WARDENBOT_CANARY` | you | A fixed canary, used as is |
| `WARDENBOT_UPDATE_SNAPSHOTS` | you | `1` writes or refreshes `assert_prompt_shape` snapshots |
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | `install()` | The endpoint's URL and the dummy key `wardenbot-mock` |
| `WARDENBOT_ORIGINAL_OPENAI_BASE_URL`, `WARDENBOT_ORIGINAL_OPENAI_API_KEY` | `install()` | Your original values: the upstream and its key |
| `WARDENBOT_ENDPOINT` | `install()` | The endpoint's pid and URL, so child processes start their own |
| `NO_PROXY`, `no_proxy` | `install()` | Gain the loopback hosts, so proxies don't intercept the endpoint |

The upstream URL is `WARDENBOT_UPSTREAM_BASE_URL`, else the original
`OPENAI_BASE_URL`, so a key meant for another OpenAI-compatible provider is
never sent to OpenAI, else `https://api.openai.com`.

## pytest integration

When the endpoint is configured, the plugin calls `install()` from
`pytest_load_initial_conftests`, before any `conftest.py` is imported and
before pytest-django runs `django.setup()`. Each pytest-xdist worker gets its
own endpoint. The endpoint the plugin installed is removed when the session
ends.

- `@pytest.mark.wardenbot_model(script=..., mutate=..., case=...)` with the
  `wardenbot_model` fixture runs the test inside a `model_endpoint` block named
  after the test (or `case`). The fixture yields the block, so
  `wardenbot_model.requests` holds the captured requests.
- The terminal summary shows the mode, the folder and the request count. An
  endpoint error no test could raise, such as a miss outside any block, fails
  the run.

## Egress guard

In `scripted` and `replay`, `install()` refuses `api.openai.com`, the host of
the original `OPENAI_BASE_URL`, and `guard_hosts`: name resolution for guarded
hostnames, and connections to guarded addresses. A host given with a port is
guarded on that port only; a loopback host (a local model server) is guarded
under every spelling, on its port. The enclosing block raises
`EgressBlockedError`, naming the host. The guard can't see traffic sent
through an HTTP proxy.

## Command line

```bash
python -m pytest_wardenbot.model check FOLDER
```

Scans a response folder for credentials, validates its manifest and `.jsonl`
files, and reports missing rule files and shadowed rules. Exits 1 on any
problem.
