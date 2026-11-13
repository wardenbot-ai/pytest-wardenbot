---
description: Every public class, function and constant, with the module to import it from.
---

# API reference

Generated from docstrings. Every name on this page is public and covered by
the [versioning and stability policy](stability.md). Import each name from the
module named at the top of its section; other module paths are internal and
can change without notice.

## Core

Import from `pytest_wardenbot`.

::: pytest_wardenbot
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "__version__"
        - "ChatbotAdapter"
        - "AsyncChatbotAdapter"
        - "ChatbotResponse"
        - "WardenBotError"
        - "WardenBotConfigError"
        - "WardenBotInfraError"

## Adapters

Import from `pytest_wardenbot.adapters`.

::: pytest_wardenbot.adapters
    options:
      show_root_heading: false
      heading_level: 3
      members: ["HTTPChatbotAdapter", "AsyncHTTPChatbotAdapter", "to_sync"]

### Vendor adapters (optional extras)

Adapter modules import without vendor SDKs; SDK-backed default clients need
the matching extra when you construct them. The legacy Assistants adapters need
an injected compatible client. See [Add your chatbot](../how-to/add-chatbot.md)
and [dependency support](../how-to/dependency-support.md) for usage and tested
versions.

| Class (sync / async) | Import from | Extra |
|---|---|---|
| `OpenAIResponsesAdapter` / `AsyncOpenAIResponsesAdapter` | `pytest_wardenbot.adapters.openai_responses` | `[openai]` |
| `OpenAIChatAdapter` / `AsyncOpenAIChatAdapter` | `pytest_wardenbot.adapters.openai_chat` | `[openai]` |
| `OpenAIAssistantsAdapter` / `AsyncOpenAIAssistantsAdapter` | `pytest_wardenbot.adapters.openai_assistants` | `[openai]` |
| `AnthropicMessagesAdapter` / `AsyncAnthropicMessagesAdapter` | `pytest_wardenbot.adapters.anthropic_msgs` | `[anthropic]` |
| `LangChainAdapter` / `AsyncLangChainAdapter` | `pytest_wardenbot.adapters.langchain_runnable` | `[langchain]` |

OpenAI retired the public Assistants API on 26 August 2026. The legacy adapter
classes still import, but constructing one without an injected compatible
client raises an infrastructure error. See
[OpenAI migration](../how-to/migrate-openai.md). The Responses adapters keep
local session histories; reset clears them and doesn't delete old remote
threads. For LangGraph state and reset hooks, see
[the graph recipe](../how-to/langgraph-state.md).

::: pytest_wardenbot.adapters.openai_responses
    options:
      show_root_heading: false
      heading_level: 4

::: pytest_wardenbot.adapters.openai_chat
    options:
      show_root_heading: false
      heading_level: 4

::: pytest_wardenbot.adapters.openai_assistants
    options:
      show_root_heading: false
      heading_level: 4

::: pytest_wardenbot.adapters.anthropic_msgs
    options:
      show_root_heading: false
      heading_level: 4

::: pytest_wardenbot.adapters.langchain_runnable
    options:
      show_root_heading: false
      heading_level: 4

## Local model servers

Import from `pytest_wardenbot.local`. See
[Run against local models](../how-to/local-models.md).

::: pytest_wardenbot.local
    options:
      show_root_heading: false
      heading_level: 3

## Model endpoint for pipeline tests

Import from `pytest_wardenbot.model`. A local OpenAI-compatible endpoint that
serves scripted replies to the application's own SDK client and captures
every request it sends. No pytest import, so it also works under `unittest`
and Django's test runner.

::: pytest_wardenbot.model
    options:
      show_root_heading: false
      heading_level: 3

## Business truth

Import from `pytest_wardenbot.business_truth`.

::: pytest_wardenbot.business_truth
    options:
      show_root_heading: false
      heading_level: 3

## Deterministic grading

Import from `pytest_wardenbot.grading.deterministic`. The same names are also
exported by `pytest_wardenbot.grading`. Measured accuracy and known misses:
[Grading accuracy](grading-accuracy.md).

::: pytest_wardenbot.grading.deterministic
    options:
      show_root_heading: false
      heading_level: 3

## Canary tokens

Import from `pytest_wardenbot.canary`.

::: pytest_wardenbot.canary
    options:
      show_root_heading: false
      heading_level: 3

## LLM judge (optional `[judge]` extra)

Import from `pytest_wardenbot.grading.judge`. See
[Enable LLM-judge tests](../how-to/llm-judge-setup.md).

::: pytest_wardenbot.grading.judge
    options:
      show_root_heading: false
      heading_level: 3

## Attack runners

Import from `pytest_wardenbot.runners`. The legacy boolean runner stays
compatible. New agent integrations use the agent contracts below; see
[agent trials](../how-to/agent-trials.md).

::: pytest_wardenbot.runners
    options:
      show_root_heading: false
      heading_level: 3
      members: ["run_probes", "ProbeResult", "ProbeOutcome", "AttackRunner", "AttackResult"]

## Agent trials

Import from `pytest_wardenbot.agents`. Outcomes and reason codes are explained
in [Agent outcomes and reason codes](agent-outcomes.md).

::: pytest_wardenbot.agents
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "AgentTarget"
        - "TargetRun"
        - "Scenario"
        - "AttackSurface"
        - "AgentCapability"
        - "CapabilityUnavailable"
        - "RunLimits"
        - "run_scenario"
        - "RunResult"
        - "Outcome"
        - "ReasonCode"
        - "Exposure"
        - "HarnessTrace"
        - "AgentEvent"
        - "EventKind"
        - "EventProvenance"
        - "EventTrust"
        - "evaluate"
        - "required_capabilities"
        - "PrivacyPolicy"
        - "format_result"
        - "render_result_html"
        - "result_to_dict"
        - "result_to_json"
        - "to_legacy_attack_result"

## Bounded campaigns

Import from `pytest_wardenbot.agents`. See
[campaign execution](../how-to/agent-campaigns.md) for instrumentation,
resource ownership and retry safety.

::: pytest_wardenbot.agents
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "CampaignLimits"
        - "ExecutionBudget"
        - "TrialContext"
        - "RetryPolicy"
        - "BudgetExceeded"
        - "RateLimitError"
        - "current_trial_context"
        - "CampaignCase"
        - "TrialResources"
        - "TrialRecord"
        - "TrialState"
        - "CampaignResult"
        - "run_campaign"
        - "campaign_to_dict"
        - "campaign_to_json"

## Portable evidence

Import from `pytest_wardenbot.agents`. See
[evidence bundles](../how-to/evidence-bundles.md) for privacy defaults,
re-grading limits and the difference between saved evidence and a new run.

::: pytest_wardenbot.agents
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "EVIDENCE_SCHEMA_VERSION"
        - "EVIDENCE_GRADER_VERSION"
        - "EvidenceBundle"
        - "EvidenceComparison"
        - "ReplayManifest"
        - "create_evidence_bundle"
        - "load_evidence_bundle"
        - "evidence_to_json"
        - "evidence_to_dict"
        - "regrade_evidence"
        - "compare_evidence"
        - "comparison_to_dict"
        - "make_replay_manifest"
        - "execute_fixture"
        - "replay_evidence"
        - "evidence_fingerprint"
        - "render_evidence_html"
        - "evidence_to_junit"

## Application packs

Import from `pytest_wardenbot.agents.packs` (also exported by
`pytest_wardenbot.agents`). See
[application boundaries](../how-to/application-packs.md) for the required
hooks, identity and approval scope, and the four control behaviors.

::: pytest_wardenbot.agents.packs
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "ApplicationPack"
        - "ApplicationPackSpec"
        - "application_spec"
        - "APPLICATION_PACKS"
        - "APPLICATION_SCENARIOS"
        - "SyntheticIdentity"
        - "ApplicationRole"
        - "ALPHA_EDITOR"
        - "ALPHA_VIEWER"
        - "BETA_EDITOR"
        - "ApplicationSnapshot"
        - "ApplicationHarness"
        - "ApplicationTrial"
        - "ApplicationSession"
        - "ScriptedApplicationTarget"

## Controlled MCP harness (optional `[mcp]` extra)

Import from `pytest_wardenbot.mcp`. See [the harness guide](../how-to/mcp-harness.md)
for the tested SDK and protocol matrix, and
[Connect your own agent](../how-to/custom-agent.md) for `TrialTools`.

::: pytest_wardenbot.mcp
    options:
      show_root_heading: false
      heading_level: 3
      members:
        - "MCPHarness"
        - "SUPPORTED_PROTOCOL_VERSIONS"
        - "MCP_SURFACES"
        - "LIFECYCLE_SURFACES"
        - "MCPClient"
        - "TrialTools"
        - "ToolSpec"
        - "TurnLimitReached"
        - "ScriptedMCPAgentTarget"

## Agent framework targets

### LangGraph (optional `[langgraph]` extra)

Import from `pytest_wardenbot.targets.langgraph`. See
[Test a LangGraph agent](../how-to/langgraph-agent.md).

::: pytest_wardenbot.targets.langgraph
    options:
      show_root_heading: false
      heading_level: 4

### Claude Agent SDK (optional `[claude-agent]` extra)

Import from `pytest_wardenbot.targets.claude`. See
[Test a Claude Agent SDK agent](../how-to/claude-agent.md).

::: pytest_wardenbot.targets.claude
    options:
      show_root_heading: false
      heading_level: 4

## Corpora

Import from `pytest_wardenbot.corpus`. See
[Customize the attack corpora](../how-to/customize-corpora.md).

::: pytest_wardenbot.corpus
    options:
      show_root_heading: false
      heading_level: 3
