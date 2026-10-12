# Evaluation evidence and interpretation

The repository retains historical text detector results, a Responses/MCP application pilot and a direct support application pilot. Their denominators and assertions differ. They are not interchangeable benchmarks, current model rankings or production safety scores.

## Historical text evaluation: May 26, 2026

The archived v0.1 evaluation used `gpt-4o-mini`, `claude-haiku-4-5` and a deliberately vulnerable local stub with the then-configured support-bot prompts. The historical run used temperature 0; current adapter/model settings need not match it. Original artifacts remain in `scripts/evaluation/results/`.

| Historical bot | Passed | Failed | Skipped | Collected |
| --- | ---: | ---: | ---: | ---: |
| `openai-gpt-4o-mini` | 31 | 1 | 2 | 34 |
| `anthropic-haiku-4-5` | 29 | 3 | 2 | 34 |
| `vulnerable-stub` | 0 | 32 | 2 | 34 |

These overall counts contain 29 security-related deterministic nodes, three business-fact nodes and two skipped optional nodes. The earlier 29-node security subset was 28 passed/1 failed for OpenAI, 26 passed/3 failed for Anthropic and 0 passed/29 failed for the stub. Do not combine subset counts with the 34-node collected denominator.

The OpenAI failure was the off-topic essay case. The three Anthropic failures were ROT13, leetspeak and hexadecimal detector matches. These did not independently establish execution of decoded instructions. For example, the archived ROT13 response quoted the decoded directive while also refusing it. A quoted trigger can fire a lexical check; the archive contains no instrumented sink from which to infer a committed effect.

The stub confirms that the patterns detect that constructed response, not a population false-negative rate. Its archived multi-turn warnings also expose the state limitation: successful priming requires a session-aware integration. Proposed prompt fixes were not validated by these counts alone.

To repeat the text workflow from a source checkout, inspect the bot configuration, install its provider extras and evaluation conveniences, then run `python -m scripts.evaluation.run`. It can make paid provider requests and writes a new report. Preserve the dated archive. Current cost depends on provider/model, usage and retries; the old approximate pricing table is not a current estimate or spending cap.

## Two application examples

| Application | Observation boundary | Evidence |
| --- | --- | --- |
| Responses/MCP document agent | Actual tool traffic and committed local MCP sink effects. | [Frozen reference pilot and October observations](agent-pilot.md). |
| Direct support/knowledge application | Model-generated calls to retrieval, ticket and scoped approval APIs; actual ticket mutations. | [Support pilot methodology and results](support-pilot.md). |

Both have safe/vulnerable profiles and offline controls. Application safeguards materially affect results: the MCP allowlist and support write/approval enforcement are not intrinsic model robustness. The support example has no MCP transport. Scripted controls also exercise memory, identity and role boundaries; the live two-case pilot does not cover every pack or OWASP category.

## Denominators and uncertainty

Report every planned row, including errors, unsupported cases, missing exposure and `not_run`. Utility success is separate from resistance. A clean row with no attack delivery can have inconclusive security status while its legitimate task succeeds.

Conditional rates need eligible denominators and exclusion counts. A forbidden effect in a benign quoted/encoded task is a real application violation. A false alarm requires a grading claim unsupported by the observed boundary, not just a surprising benign result. The support pilot's conservative zero-effect calibration excludes legitimate approved writes, missing traces, errors and observed effects; it is not a production false-positive-rate estimate.

Small repeated samples show mechanics and local variability. Nominal Wilson intervals describe observed counts under a binomial working model; related cases and shared model/configuration can be dependent. They do not prove independent trials, exhaustive attack coverage or model-wide rankings. Empty eligible denominators remain unavailable.

The [coverage matrix](coverage.md) separates tested local boundaries from untested categories. [Evidence bundles](../how-to/evidence-bundles.md) support review and offline regrading only when required observations survive redaction. Regrading is not new model execution, and checksums do not authenticate saved claims.
