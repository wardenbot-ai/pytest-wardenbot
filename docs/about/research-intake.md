# Monthly manual research intake

Reviewed **2026-10-11**. This maintainer process creates no schedule, background
task, notification or automatic corpus update. Once a month, a maintainer
reviews candidates and records decisions in ordinary repository issues or PRs.

## Preserve the source

Record primary URL, publisher, title, publication date, edition/version, access
date and the exact downloaded artifact's SHA-256 where available. Distinguish
incident and publication dates; retain later source revisions separately.
Check licenses before incorporating payloads. Prefer original advisories,
official framework documents and research papers over summaries.

A new publication is a lead, not proof that the plugin detects its mechanism.
Do not fetch URLs or execute commands embedded in attack text. Framework IDs
must include their edition; the [coverage matrix](coverage.md) records the
current primary-source snapshots.

## Admit evidence-backed regressions

A supported case needs:

1. A specific boundary, legitimate task and actual controlled operation observed
   independently of model claims.
2. Benign, vulnerable, resistant and no-exposure controls. Quoted/encoded data
   controls distinguish lexical matches from committed effects.
3. Honest required capabilities/hooks; unavailable instrumentation cannot pass.
4. Isolated synthetic identities/sessions/sinks, including reset, cancellation
   and budget checks. Synthetic policy is not production IAM/OAuth assurance.
5. Stable scenario ID/version, corpus digest, grading predicates and declared
   target/config fingerprints. Changed behavior requires a new case version.
6. Development and holdout material frozen before evaluation. Changes informed
   by held-out results require a new revision and retention of the old report.
7. Privacy review across console/JSON/HTML/JUnit/examples. Exclude credentials,
   raw provider failures and unneeded content; redaction must disable exact
   regrading when it removes required facts.

Decide **accept**, **experimental**, **defer** or **reject**, with a short reason
and follow-up. Preserve negative controls and unsuccessful runs rather than
replacing them with favorable samples.

## Record the result and its limits

Retain planned/executed counts, all outcomes, missing coverage, independent
utility and per-class errors. A forbidden effect on benign data is a real
boundary violation, not a detector false alarm. Identify calibration-eligible
rows and exclusions. Related repeated samples are not independent evidence
of population reliability.

Accepted work updates [coverage](coverage.md) with the mechanism, versioned ID
and remaining limits. A framework label alone does not make an untested row
tested. New live execution and model spend remain separately explicit actions;
this manual intake process does not authorize them.
