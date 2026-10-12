# Versioned coverage and its limits

Checked on **2026-10-11**. This is the maintainers' mapping of specific bundled
mechanisms to the official OWASP editions below. It is not an OWASP endorsement,
certification or claim to cover an entire Top 10 category.

**Tested** means a named local boundary has benign, vulnerable, resistant and
no-exposure controls. **Partial** means those controls cover only part of a
broader category. **Untested** means no bundled instrumented scenario establishes
coverage of that category. A pass says nothing about omitted scenarios or
production boundaries.

## Source snapshots

| Publication | Retrieved edition | PDF SHA-256 |
| --- | --- | --- |
| [OWASP Top 10 for LLM Applications 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) | [Official PDF](https://genai.owasp.org/download/56857/?tmstv=1785822482), Version 2026, contents pp. 3–4. Resource page: August 3, 2026. Cover: August 4, with a publication-date placeholder still present. This records the retrieved content without resolving that discrepancy. | `ef87993a4e50ae9d83b41ff7a3d3e6320a82dfa8d4ec6bf98d0ce264b2e6108e` |
| [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | [Official PDF](https://genai.owasp.org/download/52117/?tmstv=1765059207), Version 2026, December 2025, contents pp. 3–5. Resource page: December 9, 2025. | `a2db94cd00b08e0b3a5e5b619afe024bdbcd74503111085705e4f3dd886fcb5c` |

IDs and category names are attributed to those OWASP publications. LLM 2026
numbering differs from 2025. Hashes identify exact downloaded content; mutable
URLs can change and hashes do not authenticate a report's origin.

## Tested local scenario inventory

All thirteen boundaries below have local controls. Their category mappings
remain partial where OWASP describes mechanisms outside those controls.
Delivery means receipt at the integration, not independently observed model
processing.

| Versioned scenario | Observed boundary | Limit |
| --- | --- | --- |
| `mcp.tool-result.forbidden-tool@1` | Poisoned result induces forbidden local sink operation. | Declared tool and sink only. |
| `mcp.tool-result.canary@1` | Result-delivered synthetic canary reaches a tool effect. | No arbitrary private-data assessment. |
| `mcp.tool-description.forbidden-tool@1` | Poisoned metadata induces forbidden sink operation. | No dependency/provenance assurance. |
| `mcp.tool-description.canary@1` | Metadata-delivered synthetic canary reaches sink. | No exhaustive exfiltration channels. |
| `mcp.resource.forbidden-tool@1` | Resource delivery induces forbidden sink operation. | Requires resource consumption hooks. |
| `mcp.resource.canary@1` | Resource-delivered synthetic canary reaches sink. | No vector-index or real-data assessment. |
| `mcp.prompt.forbidden-tool@1` | MCP prompt delivery induces forbidden sink operation. | Requires MCP prompt consumption hooks. |
| `mcp.prompt.canary@1` | Prompt-delivered synthetic canary reaches sink. | No hidden system/reasoning-context claim. |
| `application.retrieval.poisoned-document@1` | Retrieved instructions induce unauthorized ticket mutation. | Plain documents; no vector store/ranking. |
| `application.memory.cross-session@1` | Persisted content read in a later clean session induces mutation. | Trial-local memory, not cross-process durability. |
| `application.identity.cross-tenant@1` | Bound principal reads peer tenant's synthetic private record. | Synthetic policy, not IAM/OAuth/authentication. |
| `application.identity.viewer-write@1` | Viewer attempts write despite valid scoped approval. | Fixed viewer/editor policy. |
| `application.approval.before-write@1` | Exact actor/tenant/operation/arguments and single-use grant gate writes. | Fixture approvals, not human UI/decision study. |

The eight MCP scenarios remain the default. Five
[application scenarios](../how-to/application-packs.md) are opt-in and declare
their required hooks. See [selection and required
coverage](../how-to/agent-scenarios.md).

## LLM Applications 2026

| Category | Coverage | Evidence and limitation |
| --- | --- | --- |
| LLM01:2026 Prompt Injection | Partial | Eight MCP cases above and `application.retrieval.poisoned-document@1`: controlled indirect delivery and effects, not every modality or novel attack. |
| LLM02:2026 Sensitive Information Disclosure | Partial | Four MCP canary cases and `application.identity.cross-tenant@1`: synthetic local disclosures, not arbitrary personal data or provider reasoning. |
| LLM03:2026 Excessive Agency | Partial | MCP forbidden-tool cases, `application.identity.viewer-write@1`, `application.approval.before-write@1`: limited dispatch/authorization gates, not whole-application agency. |
| LLM04:2026 Supply Chain | Untested | Metadata injection is mapped to injection. No artifact, dependency, vendor or deployment supply-chain assessment. |
| LLM05:2026 Data and Model Poisoning | Untested | Retrieved text is inference-time injection; no training data, fine-tuning or model-weight poisoning. |
| LLM06:2026 Unbounded Consumption | Untested target risk | [Campaign limits](../how-to/agent-campaigns.md) safeguard the evaluation's cooperative attempts, turns and deadlines. They do not test target resource-exhaustion vulnerability, hidden requests or provider spending limits. |
| LLM07:2026 Misinformation | Untested | Expected-fact utility is not semantic truth or misinformation assessment. |
| LLM08:2026 Hidden Context Exposure | Untested | Agent canaries do not establish hidden system/developer-prompt or reasoning secrecy. Optional text canaries are separate application-configured checks. |
| LLM09:2026 Vector and Embedding Weaknesses | Untested | No embedding geometry, vector database, index isolation or ranking implementation. |
| LLM10:2026 Improper Output Handling | Partial | Controlled function calls pass schema/dispatch and write gates; no general SQL/browser/shell/downstream-sink testing. |

## Agentic Applications 2026

| Category | Coverage | Evidence and limitation |
| --- | --- | --- |
| ASI01 Agent Goal Hijack | Partial | MCP pairs and `application.retrieval.poisoned-document@1`: task diversion into local action, not full planner/long-horizon goal instrumentation. |
| ASI02 Tool Misuse and Exploitation | Partial | MCP forbidden-tool cases and `application.approval.before-write@1`: controlled tool/write misuse, not arbitrary tool chains/services. |
| ASI03 Identity and Privilege Abuse | Partial | `application.identity.cross-tenant@1`, `application.identity.viewer-write@1`, `application.approval.before-write@1`: synthetic principal/permission/grant scope, not production delegated credentials. |
| ASI04 Agentic Supply Chain Vulnerabilities | Untested | No registry, package/server provenance or third-party agent supply-chain assessment. |
| ASI05 Unexpected Code Execution (RCE) | Untested | No shell/interpreter target. Inert bundle loading is not target RCE coverage. |
| ASI06 Memory & Context Poisoning | Partial | `application.memory.cross-session@1`: actual persistence and later clean-session read; no distributed/production long-term memory. |
| ASI07 Insecure Inter-Agent Communication | Untested | No peer-agent channel, authentication or delegation protocol. MCP transport alone is not such a test. |
| ASI08 Cascading Failures | Untested | Local cleanup does not establish containment across connected agents/services. |
| ASI09 Human-Agent Trust Exploitation | Untested | Fixture approval gates do not test human deception or decision quality. |
| ASI10 Rogue Agents | Untested | Vulnerable controls follow injected inputs; no autonomous misalignment without active attacker. |

## What application samples add

The [Responses/MCP reference](agent-pilot.md) and
[direct support application](support-pilot.md) demonstrate different integrations.
Live samples cover only their frozen cases, not every row above. Scripted and
SDK-offline controls verify mechanics, not model robustness.

Outcomes, utility, errors, unsupported cases, missing exposure and unexecuted
rows stay separate. [Evidence bundles](../how-to/evidence-bundles.md) permit
offline regrading only when required observations survive redaction. Saved
provenance and checksums do not authenticate a trace.
