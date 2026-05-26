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

These bundled adapters require their vendor SDK extra to import, so they are
not auto-documented here (the docs build doesn't install the vendor SDKs).
See [Add your chatbot](../how-to/add-chatbot.md) for usage.

| Class (sync / async) | Module | Extra |
|---|---|---|
| `OpenAIChatAdapter` / `AsyncOpenAIChatAdapter` | `pytest_wardenbot.adapters.openai_chat` | `[openai]` |
| `OpenAIAssistantsAdapter` / `AsyncOpenAIAssistantsAdapter` | `pytest_wardenbot.adapters.openai_assistants` | `[openai]` |
| `AnthropicMessagesAdapter` / `AsyncAnthropicMessagesAdapter` | `pytest_wardenbot.adapters.anthropic_msgs` | `[anthropic]` |
| `LangChainAdapter` / `AsyncLangChainAdapter` | `pytest_wardenbot.adapters.langchain_runnable` | `[langchain]` |

The OpenAI Assistants API is deprecated (sunset 2026-08-26); constructing
`OpenAIAssistantsAdapter` emits a `DeprecationWarning`. Prefer
`OpenAIChatAdapter` for new work.

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
        - "semantic_equivalence_case"
        - "brand_alignment_case"
        - "hallucination_case"
        - "off_policy_case"
        - "refusal_quality_case"

## Attack runners

::: pytest_wardenbot.runners.base
    options:
      heading_level: 3
      members: ["AttackRunner", "AttackResult"]

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
