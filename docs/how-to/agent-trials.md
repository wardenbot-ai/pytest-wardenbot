# Instrumented agent trials

The `pytest_wardenbot.agents` API adds structured trials for applications that
use tools. It is separate from the existing `ChatbotAdapter` and shipped text
tests. Core contracts require no MCP or provider SDK, credentials, or community
notification webhooks.

Use the [packaged agent scenarios](agent-scenarios.md) for versioned pytest nodes,
paired benign/attack cases and required-coverage checks. The
[MCP harness guide](mcp-harness.md) covers the controlled integration; the
[reference agent](reference-agent.md) connects a model to the real tool loop.

## Outcomes and evidence

| Outcome | Meaning |
| --- | --- |
| `VIOLATED` | Trusted instrumentation recorded the asserted forbidden effect or synthetic canary at the recording sink. |
| `RESISTED` | The injected surface was delivered, the declared boundary trace is complete, and no asserted violation was recorded there. |
| `INCONCLUSIVE` | Exposure, required processing evidence, or complete boundary coverage is missing. |
| `UNSUPPORTED` | The target lacks a capability the scenario requires. |
| `ERROR` | Setup, execution, reset, limits, observations, or returned data failed. |

`task_succeeded` is an independent, target-reported utility signal. A target
that refuses everything can resist the recorded attack while failing its
legitimate task. `RESISTED` is not a claim about uninstrumented tools or a whole
application's security.

`Exposure.DELIVERED` means the harness delivered the scenario's injected surface.
It does not prove that a language model processed it. Set
`Scenario(require_processing=True, ...)` when independently instrumented
processing is required; without such evidence the result is inconclusive.

An `AgentEvent` records its kind, trial, provenance and observation trust.
Delivery and processing evidence must also match the scenario ID and version;
an unrelated benign tool response cannot establish injected-content exposure.
Observation integrity and content authority are separate: a faithfully recorded
tool response can still contain attacker-controlled instructions.

The evaluator accepts two separate inputs:

- `TargetRun` contains the application's claims, final text and optional events.
  Its event labels are normalized to target-reported/untrusted, even if the
  target supplied `HARNESS` or `OBSERVED` labels.
- `HarnessTrace` comes from trusted test instrumentation and its recording
  sink. Only this separate input can establish exposure and effects. A complete
  trace covers the declared local boundary, not arbitrary external tools.

Do not construct a trusted trace by parsing model output. This API defines an
integration trust boundary; it does not sandbox malicious Python code running
inside the same process. A claimed tool call or a canary repeated in final text
alone does not prove a recorded effect.

## Implement a target

An `AgentTarget` exposes a name and `frozenset[AgentCapability]`, plus:

```python
async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
    ...

async def reset(self, trial_id: str) -> None:
    ...
```

Declare `ISOLATED_STATE` when reset genuinely establishes clean per-trial state,
including a no-op for a stateless integration. Declare the surfaces your target
can consume. The runner requires isolation and the scenario's surface capability
in addition to explicitly requested capabilities.

Use `run_scenario(target, scenario, observe=harness.observe, limits=RunLimits(...))`.
The observer is a trusted, local, nonblocking callback returning a `HarnessTrace`
for the supplied trial ID. Without it, successful target execution remains
inconclusive. The runner creates unique IDs and calls reset before and after
supported execution, including failures and cancellation. Unsupported targets
return without starting execution or creating target state.

`RunLimits` defaults to a 30-second execution deadline, ten turns and a separate
five-second cleanup deadline. Integrations must enforce `max_turns` inside their
own loops and report actual turns; over-limit reports are rejected. Set
`TargetRun(limit_exhausted=True, ...)` when the budget prevents a
planned next step. That produces an execution error rather than resistance,
even when the reported turn count equals the limit. Completing the task exactly
at the limit is allowed when no step was cut short. Async
deadlines require cooperative cancellation. Blocking code or an integration
that suppresses cancellation requires external process isolation.

Caller cancellation propagates as `CancelledError` after cleanup is attempted.
Ordinary exceptions become fixed reason codes, without raw messages or chained
provider exceptions. A confirmed effect remains `VIOLATED` if execution or cleanup
subsequently fails, with the additional error reason recorded.

## Use results in pytest

An application-owned async test can use the runner with `pytest-asyncio`:

```python
import pytest
from pytest_wardenbot.agents import Outcome, format_result, run_scenario

@pytest.mark.asyncio
async def test_agent_boundary(agent_target, attack_scenario, trusted_harness):
    result = await run_scenario(
        agent_target, attack_scenario, observe=trusted_harness.observe
    )
    assert result.outcome is Outcome.RESISTED, format_result(result)
    assert result.task_succeeded is True, format_result(result)
```

The fixtures above belong to your integration; the plugin does not silently
invent them. This strict assertion returns nonzero for missing coverage and
execution errors as well as violations. The reason codes distinguish those
cases. A call-phase assertion is a pytest failure; setup exceptions are errors.
The five domain outcomes are not five native pytest status categories.

## Keep diagnostics private

Use `format_result`, `result_to_dict`, `result_to_json`, or `render_result_html`.
They hide event names, arguments, text payloads and usage data by default, while
retaining outcome, exposure, reason codes and structural IDs. IDs should be
non-sensitive labels. HTML output escapes its content and has no active scripts.

For an intentional diagnostic capture of sanitized content:

```python
from pytest_wardenbot.agents import PrivacyPolicy, result_to_json

policy = PrivacyPolicy(
    secrets=("your-synthetic-test-canary",),
    include_content=True,
    max_text_chars=1000,
)
sanitized_json = result_to_json(result, policy=policy)
```

Literal secrets are replaced before truncation. Sensitive dictionary keys are
masked, unknown objects are omitted, and nesting/item counts are bounded. Opt-in
capture cannot identify arbitrary unrecognized personal information. Internal
event data, `dataclasses.asdict`, custom logging, and third-party SDK logs are
outside these output helpers. Existing chatbot diagnostics retain their
documented behavior; this policy applies to the new agent result path.

These small diagnostic exports are not yet replayable evidence bundles.

## Migrate a boolean result consumer

Existing `AttackRunner`, `AttackResult(succeeded=...)` and chatbot interfaces
remain available with unchanged signatures. New agent integrations consume
`RunResult` directly rather than implementing the legacy boolean runner seam.

The explicit `to_legacy_attack_result(result)` bridge emits a deprecation warning.
It converts `VIOLATED` to `succeeded=True` and `RESISTED` to `False`. It raises
`WardenBotInfraError` for inconclusive, unsupported or error outcomes, because
those cannot safely become a boolean “attack failed.” Its details use default
content-minimized export. A legacy `False` result cannot be upgraded into evidence
of resistance without a new instrumented trial.
