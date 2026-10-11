# Reference model agent over MCP

Install `pytest-wardenbot[mcp,openai]` and run from a release source checkout:

```bash
python examples/mcp_agent/run_controls.py --transport stdio --samples 2
```

This default is offline: a deterministic simulator sits behind the actual
OpenAI SDK HTTP transport, while tools run through the real MCP SDK. It checks
safe and deliberately vulnerable integrations, paired benign/attack trials,
and separate development/holdout cases. It makes no provider requests and reads
no credentials or `.env` files. A JSON report is emitted; exit zero means every
expected control and expected-fact task check succeeded.

To evaluate the same frozen cases with a real model, put `OPENAI_API_KEY` in the
process environment and explicitly opt into live requests:

```bash
python examples/mcp_agent/run_controls.py --live \
  --model gpt-5.4-mini-2026-03-17 --samples 2 \
  --max-calls 64 --max-output-tokens 512 \
  --timeout 30 --campaign-timeout 180 --max-turns 8 \
  --reasoning none --output pilot.json
```

Live mode is billable. The SDK retries are disabled. Reports preserve errors,
inconclusive outcomes, and unexecuted trials when a campaign limit is reached.
Exit one means some expected controls did not succeed; retain that report.

`reference_agent.py` contains the application-owned Responses tool loop. Its
safe profile enforces a dispatch allowlist; its vulnerable profile deliberately
trusts MCP metadata/results. Only actual, validated local sink execution proves
an effect. These profiles do not measure model robustness in isolation.

The full setup, lifecycle contract, and migration recipe are in
[`docs/how-to/reference-agent.md`](../../docs/how-to/reference-agent.md).
The methodology is in
[`docs/about/agent-pilot.md`](../../docs/about/agent-pilot.md).
