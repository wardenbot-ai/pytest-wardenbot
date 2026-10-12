# Run bounded agent campaigns

`run_campaign` runs a planned sequence of isolated agent trials with shared call
and turn budgets, a wall deadline, bounded cleanup, and a result row for every
case. It uses the same outcomes and independent `task_succeeded` signal as
[single agent trials](agent-trials.md). Core campaigns require no provider SDK,
credentials, or network access.

## Run an offline campaign

This example uses the optional controlled MCP integration. Install
`pytest-wardenbot[mcp]`; it makes no model calls.

```python
import asyncio
from contextlib import asynccontextmanager

from pytest_wardenbot.agents import (
    AttackSurface, CampaignCase, CampaignLimits, Scenario, TrialResources,
    campaign_to_json, run_campaign,
)
from pytest_wardenbot.mcp import MCPHarness, ScriptedMCPAgentTarget

scenario = Scenario(
    id="campaign.document",
    version="1",
    task="Summarize quarterly sales.",
    surface=AttackSurface.TOOL_RESULT,
    forbidden_tool="record_action",
)

@asynccontextmanager
async def make_trial(context):
    harness = MCPHarness(scenario, transport="memory")
    target = ScriptedMCPAgentTarget(harness, behavior="resistant")
    # The target owns an async harness.trial context during its run, which
    # closes the MCP client/server even if execution fails or is cancelled.
    yield TrialResources(target, observe=harness.observe)

async def main():
    result = await run_campaign(
        [CampaignCase(f"sample.{i}", scenario, make_trial) for i in range(4)],
        limits=CampaignLimits(
            max_calls=20, max_turns=20, concurrency=2,
            timeout_seconds=60, cleanup_timeout_seconds=5,
        ),
    )
    print(campaign_to_json(result))

asyncio.run(main())
```

Factories receive a `TrialContext` whose generated trial ID matches the ID
passed to `target.reset`, `target.run`, and the observer. Each case needs a
distinct target object, including serial trials. The campaign keeps object
references and rejects repeated instances with `shared_target`. Each factory
must also create isolated harness, session, history, and recording resources;
distinct target objects alone do not establish that those resources are isolated.
Case IDs must be unique, non-sensitive structural labels.

## Instrument your integration

A campaign target must explicitly declare `AgentCapability.BUDGET_ACCOUNTING`.
Declare it only after instrumenting every operation intended to count against
the budget. A target without the declaration returns `UNSUPPORTED` with
`budget_instrumentation_required` before reset or execution. Existing targets
remain compatible with `run_scenario` outside a campaign.

The context is available without changing the `AgentTarget` method signatures:

```python
from pytest_wardenbot.agents import current_trial_context

async def one_model_turn(client, request):
    context = current_trial_context()
    if context is not None:
        context.turn()  # Before this turn starts any work.
        response = await context.call(lambda: client.generate(request))
    else:
        response = await client.generate(request)
    return response
```

Wrap tool discovery, model requests, tool dispatch, and other operations you
choose to count. `context.call` claims one call **before every attempt**,
including failed attempts and retries. `context.turn` claims one logical turn
before work starts. Several instrumented calls may belong to one turn. Finishing
on the final permitted call or turn is allowed; attempting another is rejected.
The synchronous claims are atomic across concurrent trials sharing one budget.
Targets still enforce their per-trial `max_turns` and report real turns in
`TargetRun`; a reported count exceeding context turn claims becomes an execution
error while any observed violation remains intact.

These caps control **instrumented operation attempts**. They cannot see hidden
SDK requests, unwrapped calls, subprocess activity, or an integration's internal
retry loop. Disable SDK automatic retries and wrap each intended attempt.
Declaring the capability is an integration contract, not a process sandbox or
proof that all remote spending is controlled. Different integrations must use
consistent operation/turn definitions before comparing counts.

## Own clients and cleanup inside the factory

The factory is an async context manager created and entered inside the running
event loop. Use `AsyncExitStack` to release partially created resources even if
setup fails or is cancelled before the factory yields:

```python
from contextlib import AsyncExitStack, asynccontextmanager

@asynccontextmanager
async def make_trial(context):
    async with AsyncExitStack() as stack:
        client = await stack.enter_async_context(make_client())
        harness = await stack.enter_async_context(make_harness(context.trial_id))
        target = make_target(client, harness)
        yield TrialResources(target, observe=harness.observe)
```

`make_client`, `make_harness`, and `make_target` above are your integration's
constructors. Do not capture one shared client/session outside the factory.
Setup is covered by the campaign wall deadline. `RunLimits.timeout_seconds`
covers reset and target execution; it does not impose a separate factory setup
timeout. Target reset cleanup and factory teardown each have their own bounded
window. Those windows may finish after the execution deadline. A cancelled
factory receives `CancelledError` through its context-manager exit.

Deadlines cancel cooperative workers, then drain target reset and factory
teardown. External cancellation propagates after owned tasks are drained,
including a second cancellation while cleanup is running. Targets and factories
must cooperate with cancellation and own/drain any tasks they create. Blocking
Python or integrations that suppress cancellation require process isolation;
the campaign cannot forcibly stop them or their remote side effects.

## Retry only declared safe rate limits

There are no retries by default and the campaign never reruns `target.run`.
`TrialContext.call` retries only `RateLimitError`, an explicit integration
classification with optional finite nonnegative `retry_after` seconds. Translate
recognized provider rate limits into this exception without attaching raw
provider error text. Generic errors, timeouts, and cancelled operations are not
retried.

```python
from pytest_wardenbot.agents import RetryPolicy

response = await context.call(
    read_operation,
    retry=RetryPolicy(max_retries=2, delay_seconds=0.1, safe_to_retry=True),
)
```

The greater of `delay_seconds` and `retry_after` is used, bounded by the remaining
campaign deadline. A delay that cannot fit stops with `campaign_deadline` before
another attempt. All attempts consume the same shared call budget. Invalid
booleans, nonfinite numbers, and contradictory retry declarations are rejected.

For a side-effecting operation, retries additionally require an explicit
idempotency declaration and a stable key:

```python
async def write_operation(*, idempotency_key):
    return await service.write(payload, idempotency_key=idempotency_key)

await context.call(
    write_operation,
    retry=RetryPolicy(
        max_retries=1, safe_to_retry=True, side_effecting=True,
        idempotent=True, idempotency_key="synthetic-write-unique-to-this-trial",
    ),
)
```

The context passes the same `idempotency_key` keyword on every attempt. The
integration must send it to a service that guarantees deduplication for this
operation and key lifetime. The library does not implement provider deduplication
or infer that a write is safe. Leave retries disabled for operations without
that guarantee. A write that commits and then fails stays recorded; a retry
policy cannot erase its actual effect.

## Account for every planned case

`CampaignResult.trials` preserves input order. Each row has a `completed`,
`cancelled`, or `not_run` state, fixed reason codes, and its independent
`RunResult` when execution/setup occurred. Exhausted budgets or deadlines leave
remaining cases `not_run`; those rows have no security outcome or utility claim.
Setup, execution, cleanup and instrumentation failures remain explicit. An actual
harness-observed effect stays `VIOLATED` even if a budget, deadline or cleanup
failure follows it.

Use `planned` as the campaign coverage denominator. `outcome_counts` counts only
rows with outcomes and `task_successes` counts separate reported utility successes;
neither excludes incomplete coverage to make a success rate look better. An
empty campaign is valid and reports zero planned cases. Applications that require
coverage must reject empty or incomplete plans explicitly. Campaign rows are an
application API and do not automatically create required pytest scenario nodes.

Call `context.record_usage` with supplied finite nonnegative numeric counters
after each response, including responses received before a later failure. Usage
is accumulated atomically; unknown usage remains `None`, rather than invented
zero tokens. If a trial supplies context usage, it is used instead of duplicate
`TargetRun.usage`. Otherwise the target's validated usage is retained. Aggregate
usage is partial when some rows have no usage; `usage_reported_trials` counts
only rows supplying recognized public usage fields. Internal custom counters
such as tool-call counts are retained for inspection but do not establish token
usage coverage; a row with only custom counters reports public usage as `None`.
An overflowing aggregate is unavailable rather than nonfinite JSON.
`estimated_cost_usd` is an estimate, **not a provider-enforced spending cap**.

Use `campaign_to_dict` or `campaign_to_json` to write reports. Defaults hide
inputs, event payloads, raw exceptions, provider messages, and idempotency keys.
Public campaign usage allows only recognized token-counter labels and
`estimated_cost_usd`; arbitrary application-supplied usage keys are omitted.
`PrivacyPolicy` provides the same explicit content opt-in and literal-secret
filtering as single-trial reports. Structural IDs must remain non-sensitive.
Raw dataclasses, SDK logs, or custom logging bypass these privacy defaults.
