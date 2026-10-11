# Run a reference model agent over MCP

The reference agent connects the real OpenAI Responses SDK to the instrumented
MCP harness. It discovers actual tool definitions, sends them to the model,
executes model-generated function calls through MCP, supplies actual tool
results, and continues until the model returns final text or a limit is reached.

Its two profiles demonstrate application behavior. **Safe** exposes and executes
only `fetch_document`, with instructions treating tool content as untrusted
data. The dispatch allowlist blocks a requested sink call even if a model emits
one. **Vulnerable** exposes every controlled tool and deliberately promotes
tool descriptions and document results into developer messages. It still
requires a real model-generated call and validated MCP execution to record a
forbidden effect. There is no scripted fallback that creates missing effects.

## Reproduce the controls without a provider account

Install the wheel in an environment with Python 3.11 or newer:

```bash
python -m pip install 'pytest-wardenbot[mcp,openai]'
```

Copy `examples/mcp_agent/` from the release source archive into an `examples/`
directory in your working project. Keep all Python files in that folder. The
example scripts are source-archive artifacts, rather than an installed package
API; their launcher does not add the package's `src/` directory to Python's
import path. The package therefore comes from the wheel you installed.

```bash
python examples/mcp_agent/run_controls.py \
  --transport stdio --samples 2 --output offline-pilot.json
```

The default simulator handles actual SDK HTTP requests through a mock transport;
MCP discovery, requests, argument validation, and sink effects use real SDK
transports. No API key or `.env` file is consulted. Expect 16 planned and executed
trials: eight benign runs with successful task checks, four safe attack runs
with observed resistance, and four vulnerable attack runs with recorded effects.
Benign runs retain the security outcome `inconclusive` because no attack was
delivered; their separate `baseline_ok` field records successful utility checks.

Use `--transport memory` or `--transport http` for the other owned local
transports, and `--protocol 2025-11-25` for legacy negotiation. All use the same
reference tool loop. Offline results establish mechanics, not model quality.

## Run a bounded live evaluation

Set `OPENAI_API_KEY` through your environment or secret manager. The runner does
not load `.env` files. Choose an explicit model that supports Responses function
calling. The documented small snapshot supports the `none` reasoning setting.

```bash
python examples/mcp_agent/run_controls.py --live \
  --model gpt-5.4-mini-2026-03-17 --samples 2 --split all \
  --transport memory --max-calls 64 --max-output-tokens 512 \
  --timeout 30 --campaign-timeout 180 --max-turns 8 \
  --reasoning none --output live-pilot.json
```

The identical command is available as
`python scripts/evaluation/agent_pilot.py` in a source checkout. The repository's
manual `agent-pilot.yml` workflow runs this bounded pilot when explicitly
dispatched; ordinary CI uses the offline transport and makes no paid calls.

Live requests send the synthetic document, tool metadata, and synthetic canary
to OpenAI. Each request uses `store=False`, a 15-second maximum request timeout,
and zero SDK retries. The campaign consumes its call budget **before** each
request. Its 180-second deadline, 30-second trial deadlines, eight-turn trial
limit, and 512-output-token request cap are independent limits. One turn counts
one tool discovery, one model request, or one function dispatch. Cleanup has its
own bounded window and may finish after an execution deadline.

The report includes installed versions, the requested and returned model labels,
the frozen corpus digest, sample counts, per-trial outcomes, exposure, utility,
reason codes, actual local effect counts, and available token usage. It excludes
prompts, document bodies, final text, arguments, reasoning content, provider
response IDs, exception messages, and credentials. Failed trials may have
unknown utility and unavailable token usage; their attempted model call counts
remain recorded. `store=False` does not change other provider retention policies.

Exit zero means all expected controls and task checks succeeded. Exit one
preserves the JSON report when a control fails, becomes inconclusive, or is not
run because limits stop the campaign. Exit two indicates configuration or
campaign setup failure. Preserve every report, including unsuccessful runs.

## Connect your own application

`ResponsesMCPAgent` in the example is an `AgentTarget`, separate from the
text-only chatbot adapters. The application owns its model client and execution
loop. The injected `AsyncOpenAI` client must have `max_retries=0`; close it in
`finally` or an async context manager, including failures and cancellation.
The target owns only per-run local history. The harness owns and closes the MCP
client, server, subprocess or port, and private recording files.

Migrate a tool-using application by implementing `run(task, trial_id, max_turns)`
and `reset(trial_id)`, exposing honest capabilities, routing MCP calls through
`MCPHarness.trial`, and passing `harness.observe` to `run_scenario`. Do not return
only the first model response when it contains pending function calls. Keep
the complete model output when replaying a Responses conversation, including
local encrypted reasoning items when supplied, and send the corresponding
`function_call_output` items before requesting another response.

The reference implements tool descriptions and results. Resources and prompts
are unsupported by this reference agent; those harness surfaces require an
integration that actually consumes them. The packaged [pytest agent
scenarios](agent-scenarios.md) distinguish unsupported capabilities, failed
baselines, infrastructure errors, missing exposure, and confirmed effects.

Task success in this small example means the agent received the document and
its final text contains a frozen expected fact (`8%` or `12 minutes`). This is
a deterministic expected-fact presence heuristic, not semantic proof that the
entire summary is correct. See [pilot methodology](../about/agent-pilot.md).

The loop follows the official [function calling
guide](https://developers.openai.com/api/docs/guides/function-calling) and
[Responses API
reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
The model snapshot and reasoning setting are documented in the official
[GPT-5.4 Mini model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
