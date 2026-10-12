# Design principles

pytest-wardenbot puts application-specific regressions in ordinary pytest workflows. Text chatbot checks and instrumented agent scenarios preserve their different evidence limits.

## Explainable grading and observed effects

Deterministic text checks expose their matching rules. A quoted trigger can match a detector without showing that an instruction was executed. Agent scenarios therefore grade actual controlled operations from a separately supplied harness trace. Target events, completion flags and final text cannot promote themselves into trusted effects.

Optional model judges can help with subjective questions. Their model, rubric, threshold and error behavior are configuration, not universal reliability guarantees. No fixed judge agreement percentage, cost multiplier or ensemble safety guarantee is assumed. Calibrate against labeled application examples before using a judge as a gate.

## Security, usefulness and availability stay separate

Agent outcomes distinguish confirmed violation, observed resistance, inconclusive evidence, unsupported integration and execution error. Task utility is independent. Expected-fact presence in the examples is a narrow heuristic, not semantic proof of summary correctness.

Missing exposure, incomplete traces, stopped campaigns and failed baselines must not disappear into a pass rate. Positive recorded effects survive later execution or cleanup failures. Required pytest coverage rejects unavailable cases without labeling them proven vulnerabilities.

## Explicit ownership and execution bounds

Targets own execution loops; harnesses own local observations. Factories create and release isolated clients, histories, stores and sessions. Memory scenarios distinguish persistence across sessions inside a trial from isolation across independent trials.

Campaign claims count instrumented attempts before work starts. Deadlines and cancellation drain cooperative owned tasks and cleanup. Blocking code, suppressed cancellation, hidden retries and unwrapped remote calls cannot be forcibly bounded by this in-process library. Retry is disabled by default; side-effect retries need a stable transmitted key and a service that actually deduplicates the operation. Dollar usage is an estimate, not a provider-enforced spending cap.

## Pytest and portable local artifacts

The plugin retains ordinary fixtures, markers, selection and CI exit behavior. The separate agent suite is opt-in. JSON bundles, static HTML and JUnit make recorded findings reviewable without reconnecting to a provider.

Offline regrading applies assertions to saved observations. Fixture replay is a separate new execution of an allowlisted local fixture. A new live application run is separate again and may produce different results. Checksums identify content; they do not authenticate an editable saved trace.

## Untrusted report content

Reports hide payloads by default, filter configured secrets and escape rendered content. Explicit capture can still contain private information. Redaction and truncation make exact regrading unavailable when required facts are lost. Core local reporting does not upload artifacts; provider adapters and optional judges use the configured integration and its external policies.

Failure guidance is maintainer-authored text. Attack payloads and model output remain inert evidence, never executable remediation, automatic imports or URLs to fetch. Review artifacts and structural labels before sharing them.

## Concrete maintenance claims

Versioned scenario IDs, corpus digests and configuration snapshots support regressions. Compatibility is checked against the documented dependency matrix; releases and deprecations are recorded in the changelog. The project does not promise a fixed monthly release day or infer production assurance from a small controlled pilot.

See [coverage](coverage.md), [evaluation](evaluation.md) and [manual research intake](research-intake.md). A passing suite is not a model-wide ranking or OWASP certification.
