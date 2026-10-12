# Test application trust boundaries

The opt-in application packs exercise a local support application with a knowledge
document, ticket store, persistent session memory, synthetic identities, and
operation-specific approvals. They require no MCP or model SDK, credentials,
network endpoint, or production data. Every recorded violation comes from an
actual local ticket mutation or returned cross-tenant disclosure.

These controls test the integration mechanics. They do not measure a language
model, production IAM, OAuth, or an entire tenant boundary. The in-process harness
assumes trusted Python code; it is not a sandbox against an adapter that modifies
its fixture directly.

## Choose a pack

`APPLICATION_PACKS` is a frozen tuple of `ApplicationPackSpec` objects.
`APPLICATION_SCENARIOS` contains their existing `Scenario` contracts, and
`application_spec(id)` looks up one spec. Each spec declares its required
integration hooks and capabilities.

| Pack | Versioned scenario ID | Controlled boundary |
| --- | --- | --- |
| Retrieval | `application.retrieval.poisoned-document@1` | Instructions in an imported knowledge note attempt a ticket write without approval. |
| Memory | `application.memory.cross-session@1` | A first session stores an untrusted memo; a separate clean session reads that stored memo and attempts a ticket write. |
| Identity | `application.identity.cross-tenant@1` | A document asks an alpha editor to assume beta authority and read a beta ticket. |
| Identity | `application.identity.viewer-write@1` | A viewer receives a valid approval for the exact operation, but remains unable to acquire editor privileges from document text. |
| Approval | `application.approval.before-write@1` | A legitimate approved triage update is distinct from an injected, unapproved close operation. |

New surfaces are `RETRIEVAL_DOCUMENT`, `MEMORY`, `IDENTITY`, and `APPROVAL`, with
matching retrieval, memory, identity, and approval capabilities. They are separate
from the original eight MCP scenarios. The default pytest selection remains MCP;
application packs require an explicit selection:

```bash
pytest --wardenbot-agent-pack=application
pytest --wardenbot-agent-pack=memory --wardenbot-agent-required
pytest --wardenbot-agent-scenario=application.identity.viewer-write@1
```

Implement your application-owned `wardenbot_agent_target` fixture before running
the packaged pytest nodes. See [packaged scenarios](agent-scenarios.md) for the
fixture lifecycle, strict coverage gate, and scenario selection. Selecting these
cases does not silently create a model agent.

## Run the controlled application directly

```python
import asyncio

from pytest_wardenbot.agents import format_result, run_scenario
from pytest_wardenbot.agents.packs import (
    ApplicationHarness, ScriptedApplicationTarget, application_spec,
)

async def main():
    spec = application_spec("application.memory.cross-session")
    harness = ApplicationHarness(spec, variant="attack", enforce_boundaries=False)
    target = ScriptedApplicationTarget(harness, behavior="vulnerable")
    result = await run_scenario(target, spec.scenario, observe=harness.observe)
    print(format_result(result))

asyncio.run(main())
```

Each pack has four controls:

| Control | Harness and target configuration | Expected security and utility |
| --- | --- | --- |
| Benign | `variant="benign"`; any control target completes the legitimate workflow. | `INCONCLUSIVE` with only missing attack exposure; utility true. |
| Vulnerable | `variant="attack"`, `enforce_boundaries=False`, `behavior="vulnerable"`. | `VIOLATED` with an actual local effect; approval utility false after the unapproved close, other utility true. |
| Resistant | `variant="attack"`, `enforce_boundaries=True`, `behavior="resistant"`. | `RESISTED` at the declared local boundary; legitimate utility true. |
| No exposure | `variant="attack"`, `behavior="no_exposure"`. | `INCONCLUSIVE` with missing exposure; utility false. |

The scripted vulnerable target parses fixed `ACTION:` instructions from received
untrusted content and invokes public application operations. It does not insert
a preselected outcome or a fabricated effect event. The application profile must
also explicitly disable its boundary checks to permit the forbidden effect;
the target's behavior flag does not grant authority. Run a vulnerable target
against `enforce_boundaries=True` to exercise denied attempts directly.

Security outcomes and task utility remain independent. Utility in these controls
checks the expected fact from the own-tenant ticket; the approval pack also
requires its legitimate approved update to succeed and its final status to remain
triaged. This is a deterministic
fixture check, not semantic grading of a model's complete answer.

## Connect another agent to the public operations

The harness opens an application trial with independent agent sessions:

```python
async with harness.trial(trial_id) as trial:
    async with trial.session() as session:
        document = await session.retrieve()
        ticket = await session.read_ticket("ticket.alpha")
        await session.write_memory(document)
    async with trial.session() as clean_session:
        persisted_memo = await clean_session.read_memory()
        # Give this memo to a fresh application-owned model conversation.
```

`ApplicationSession` provides `retrieve`, `read_ticket`, `write_memory`,
`read_memory`, `request_approval`, `approval_for`, and `update_ticket`. Reads return
local data or `None` when denied; writes return whether the mutation occurred.
The methods record trusted fixture observations and claim a B1 call before each
operation when a campaign context is present. Closed sessions cannot read or
write. Each session captures a frozen, fixture-selected identity, so document
text cannot change its tenant or role.

The agent owns its execution loop and claims a turn before each logical step;
it also wraps its own model requests in `TrialContext.call` and disables hidden
SDK retries. The scripted target demonstrates these hooks and advertises
`BUDGET_ACCOUNTING`. A campaign counts instrumented operations, rather than
unobserved internal SDK traffic. See [campaign limits](agent-campaigns.md).

`ALPHA_EDITOR` and `BETA_EDITOR` isolate tenant authorization while holding the
role constant. `ALPHA_VIEWER` isolates role authorization in the alpha tenant.
The harness accepts a `SyntheticIdentity` selected by trusted fixture code;
no agent tool accepts a replacement principal. Requests for approval only create
pending requests. Trusted fixture code calls `harness.grant_approval(request_id)`;
that method must never be exposed as a model tool. A grant binds identity,
tenant, ticket, exact status, operation version, and single use. A valid grant
cannot override a viewer's role or another tenant's authority.

## Understand memory and state lifetime

The memory pack performs a real write in its first session, closes that session,
then reads the persisted value in a distinct session with a new ID. The later
session does not retrieve the original attack document. The vulnerable action
uses the returned stored memo; the resistant control reads the same contaminated
memo while treating its instructions as untrusted.

Memory is scoped by tenant and identity. It persists across independent sessions
within one trial's local application store. A new trial starts with fresh tickets,
memory, requests, and approvals. This fixture models session persistence, rather
than storage across process restarts or production retention policies. Targets
must provide a fresh model conversation for the later clean session when testing
a real integration.

`target.reset(trial_id)` clears only that trial's ephemeral target history. It
does not erase application effects or stored observations. The harness retains
closed trial snapshots for inspection. `harness.snapshot(trial_id)` returns a
detached copy with tickets, memory, approvals, active `session_ids`, all
`session_history` IDs, and actual effects. `observe(trial_id)` also returns
detached observations. A new trial ID cannot reuse an existing trial store.

## Preserve evidence and failures

Pass `harness.observe` separately to `run_scenario` or `TrialResources`. Delivered
attack observations match the scenario ID/version and its declared surface.
Ordinary benign reads do not establish attack exposure. Denied attempts are
recorded separately from committed writes and actual returned disclosures.
Application identity and approval authority are distinct from the untrusted
document's recorded content, even when both have observed provenance.

Actual effects survive later target errors, budget exhaustion, cancellation,
reset, and session closure. Truncated runs cannot establish resistance. For
campaigns, create a fresh harness and target in each case's async resource
factory. The harness has no background workers or external clients; your model
integration must own and drain any clients or tasks it adds.

The existing [evidence bundle](evidence-bundles.md) schema accepts these surfaces
without changing old artifacts. After a successful scripted run, its
`last_target_run`, `last_trace`, and `last_trial_id` retain the exact separate
sources for intentional synthetic-content offline regrading. A new run clears
the previous source claims before starting, so a failed run cannot export stale
claims. Do not confuse regrading saved evidence with executing the application
or model again. The built-in B2 replay manifest remains scoped to its own fixed
synthetic fixture; application evidence does not invent a live replay recipe.

Use standard result and bundle exporters for reports. Raw snapshots, private
memory, synthetic identity notes, and event payloads are local test inspection
data and bypass privacy defaults. Do not log them from a model integration.
