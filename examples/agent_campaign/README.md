# Offline campaign controls

Install `pytest-wardenbot[mcp,openai]`, then obtain this examples directory along
with its sibling `examples/mcp_agent` helpers from the source distribution or
checkout. The wheel supplies the plugin; these example scripts accompany the
source. No API keys or environment configuration are needed.

Run the script by absolute path, including from outside the checkout:

```bash
cd /tmp
/path/to/venv/bin/python /path/to/pytest-wardenbot/examples/agent_campaign/run_controls.py
```

The script imports the installed plugin without adding the checkout's `src`
directory. It uses the real OpenAI SDK with an in-process mock HTTP transport,
and real local MCP servers over their memory transport. It never calls a model
service, spends money, or loads provider credentials. The synthetic SDK key only
satisfies local client construction.

Five freshly constructed targets demonstrate resistant, vulnerable and
no-exposure scripted controls, plus safe and vulnerable Responses tool loops.
The campaign caps instrumented calls and turns at 20, uses concurrency 2, and
has a 30 second deadline with a separate 5 second cleanup allowance. All SDK
retry loops are disabled. Fact presence is a deterministic utility check, and
these controls verify harness mechanics rather than model robustness.

Successful execution exits zero and writes a content-minimized JSON summary:
five planned trials, two resisted, two violated with observed local effects,
one inconclusive no-exposure case, four successful factual tasks, and 15
instrumented operations. The two Responses trials report supplied token counts;
scripted trials have unknown token usage. Unknown usage is never filled with
zero. Call counts include both model requests and observed MCP operations, not
just model requests. Nothing is saved unless you redirect stdout.

Factories own SDK clients and construct separate targets and harnesses. Each
trial has a unique ID; the runner resets target state, drains cancellation, and
closes factory resources. Budget exhaustion cannot establish resistance, and
an observed forbidden effect remains a violation even if a later call is
blocked. See the [campaign guide](../../docs/how-to/agent-campaigns.md) for the
public integration contract.
