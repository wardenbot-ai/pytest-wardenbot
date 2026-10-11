# Controlled MCP example

From this directory, install the published optional integration and run:

```bash
python -m pip install "pytest-wardenbot[mcp]"
python run_controls.py
python run_controls.py --transport stdio --protocol 2025-11-25
python run_controls.py --transport http --protocol 2026-07-28
```

When developing from a checkout, install `.[mcp]` from the repository root first.
The script uses a real MCP SDK client/server, local subprocesses or loopback HTTP
as selected. No API keys, external endpoint or announcement webhooks are needed.

Each invocation exercises four surfaces with three scripted controls:

| Control | Expected security outcome | Legitimate sales-summary task |
| --- | --- | --- |
| resistant | `resisted` | Succeeds |
| vulnerable | `violated` | Succeeds, but also records the forbidden local effect |
| no_exposure | `inconclusive` | Does not run |

Exit zero means all 12 controls behaved as expected. It does not mean all
controls were secure; the deliberately vulnerable control must produce a
recorded violation for the example to succeed. Output is sanitized JSON using
the public agent reporting helpers; payloads and arguments are hidden by default.

The recording sink has no external effects. Each trial owns a fresh server and
private temporary journal; the SDK client, subprocess/socket and journal are
closed or removed afterward. There is no paid LLM in these scripted controls.

For your own application, implement `AgentTarget.run/reset`, use the observed
client from `harness.trial(trial_id)` inside your tool loop, and pass
`harness.observe` separately to `run_scenario`. See the
[MCP harness guide](../../docs/how-to/mcp-harness.md) and
[agent contracts guide](../../docs/how-to/agent-trials.md) for boundaries and limits.
