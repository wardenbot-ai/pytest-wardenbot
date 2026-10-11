# API reference

Auto-generated from docstrings via `mkdocstrings`.

## Top-level exports

::: pytest_wardenbot
    options:
      members: ["__version__", "ChatbotAdapter", "ChatbotResponse", "BusinessTruthFact", "JudgeCase"]
      show_root_heading: false

## Adapters

::: pytest_wardenbot.adapters.base
    options:
      heading_level: 3

::: pytest_wardenbot.adapters.http
    options:
      heading_level: 3

### Vendor adapters (optional extras)

Adapter modules remain importable without vendor SDKs; SDK-backed default
clients require the corresponding extra at construction time. The legacy
Assistants adapters require an explicitly injected compatible client.
See [Add your chatbot](../how-to/add-chatbot.md) and
[dependency support](../how-to/dependency-support.md) for usage and tested versions.

| Class (sync / async) | Module | Extra |
|---|---|---|
| `OpenAIResponsesAdapter` / `AsyncOpenAIResponsesAdapter` | `pytest_wardenbot.adapters.openai_responses` | `[openai]` |
| `OpenAIChatAdapter` / `AsyncOpenAIChatAdapter` | `pytest_wardenbot.adapters.openai_chat` | `[openai]` |
| `OpenAIAssistantsAdapter` / `AsyncOpenAIAssistantsAdapter` | `pytest_wardenbot.adapters.openai_assistants` | `[openai]` |
| `AnthropicMessagesAdapter` / `AsyncAnthropicMessagesAdapter` | `pytest_wardenbot.adapters.anthropic_msgs` | `[anthropic]` |
| `LangChainAdapter` / `AsyncLangChainAdapter` | `pytest_wardenbot.adapters.langchain_runnable` | `[langchain]` |

The public Assistants API retired on 26 August 2026. Its legacy adapter imports
remain available, but construction without an injected compatible client raises
an infrastructure error. See [OpenAI migration](../how-to/migrate-openai.md).
Responses adapters maintain local session histories; reset clears those histories,
and does not delete old remote threads. For LangGraph state and reset hooks, see
[the graph recipe](../how-to/langgraph-state.md).

## Business truth

::: pytest_wardenbot.business_truth
    options:
      heading_level: 3
      members: ["BusinessTruthFact", "MatchType", "assert_truth_fact_match"]

## Grading — deterministic

::: pytest_wardenbot.grading.deterministic
    options:
      heading_level: 3
      members:
        - "REFUSAL_MARKERS"
        - "COMPLIANCE_MARKERS"
        - "assert_no_jailbreak_compliance"
        - "assert_no_system_prompt_leak"
        - "assert_response_refuses"
        - "assert_maintains_refusal_under_bypass"
        - "response_refuses"
        - "response_indicates_compliance"
        - "contains_any"
        - "contains_none"

## Grading — LLM judge (optional `[judge]` extra)

::: pytest_wardenbot.grading.judge
    options:
      heading_level: 3
      members:
        - "JudgeCase"
        - "JudgeResult"
        - "JudgeUnavailableError"
        - "judge_available"
        - "api_key_available"
        - "judge_response"
        - "assert_judge_passes"
        - "judge_ensemble"
        - "assert_judge_ensemble_passes"
        - "aggregate_verdicts"
        - "EnsembleResult"
        - "ConsensusPolicy"
        - "DEFAULT_ENSEMBLE_MODELS"
        - "semantic_equivalence_case"
        - "brand_alignment_case"
        - "hallucination_case"
        - "off_policy_case"
        - "refusal_quality_case"

## Attack runners

The legacy boolean runner remains compatible. New instrumented agent integrations
use the additive contracts below; see [agent trials](../how-to/agent-trials.md)
for outcomes, trust boundaries and explicit legacy conversion.

::: pytest_wardenbot.runners.base
    options:
      heading_level: 3
      members: ["AttackRunner", "AttackResult"]

## Instrumented agent trials

::: pytest_wardenbot.agents.contracts
    options:
      heading_level: 3

::: pytest_wardenbot.agents.runner
    options:
      heading_level: 3
      members: ["run_scenario"]

::: pytest_wardenbot.agents.reporting
    options:
      heading_level: 3

::: pytest_wardenbot.agents._privacy
    options:
      heading_level: 3
      members: ["PrivacyPolicy"]

## Controlled MCP harness (optional `[mcp]` extra)

See [the harness guide](../how-to/mcp-harness.md) for the tested SDK/protocol
matrix and [the executable example](https://github.com/wardenbot-ai/pytest-wardenbot/tree/main/examples/mcp_harness)
for offline controls. These classes are exported by `pytest_wardenbot.mcp`.

::: pytest_wardenbot.mcp.harness
    options:
      heading_level: 3
      members: ["MCPHarness", "SUPPORTED_PROTOCOL_VERSIONS"]

::: pytest_wardenbot.mcp._client
    options:
      heading_level: 3
      members: ["MCPClient"]

::: pytest_wardenbot.mcp.targets
    options:
      heading_level: 3
      members: ["ScriptedMCPAgentTarget"]

::: pytest_wardenbot.runners.async_probe
    options:
      heading_level: 3
      members: ["run_probes", "ProbeResult"]

## Corpora

::: pytest_wardenbot.corpus.jailbreak
::: pytest_wardenbot.corpus.system_prompt_leak
::: pytest_wardenbot.corpus.refusal_bypass
::: pytest_wardenbot.corpus.off_topic

## Quickstart helpers

::: pytest_wardenbot.quickstart
    options:
      heading_level: 3
      members:
        - "AVAILABLE_TEMPLATES"
        - "Template"
        - "generate"
        - "run_quickstart"
