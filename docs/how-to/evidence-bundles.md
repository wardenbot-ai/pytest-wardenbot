# Export and review portable evidence

Evidence bundles preserve a versioned scenario, recorded outcome, declared
configuration fingerprints, grader version and evidence provenance. They support
reviewing a recorded trial without reconnecting to the target. Security outcome,
task utility and missing coverage remain separate throughout export and comparison.

An evidence bundle is a saved observation, not a current safety certificate.
The bundle checksum detects accidental changes to its serialized content; it
cannot prove the identity of its author or the truth of a saved trace. Treat
bundles from other people as untrusted inputs. Import validates the supported
schema and data shape, and never imports a target class or executes code from
a bundle.

## Local commands

Create an offline public synthetic fixture artifact, then inspect it without
executing the target again:

```bash
python -m pytest_wardenbot.agents.evidence_cli fixture \
  --behavior vulnerable --include-synthetic-content --output fixture.json
python -m pytest_wardenbot.agents.evidence_cli inspect fixture.json \
  --html evidence.html --junit evidence.xml
python -m pytest_wardenbot.agents.evidence_cli regrade fixture.json --output grade.json
```

The explicit `--include-synthetic-content` flag retains only this built-in
fixture's public synthetic content to support exact regrading. CLI HTML output
still hides content by default. The vulnerable fixture is expected to violate;
its fixture command exits zero when that expected control is reproduced.
`inspect` exits zero for valid input, regardless of the stored security outcome.
`regrade` exits zero for resistance, one for a violation, and two for unavailable
coverage or an error. The generated strict JUnit reflects recorded violations
as failures even when the fixture command successfully reproduced its control.

These commands perform separate, explicit operations:

```bash
python -m pytest_wardenbot.agents.evidence_cli replay fixture.json --output replay.json
python -m pytest_wardenbot.agents.evidence_cli compare fixture.json replay.json \
  --output comparison.json --html comparison.html
```

`replay` executes the bound built-in synthetic fixture and exits zero when the
expected assertions are reproduced. `compare` produces a descriptive comparison
and exits zero even when metadata are incompatible or the observations changed;
it is not an automatic security gate. Invalid, incompatible operation requests
or unreadable files exit two with a fixed diagnostic. None of these commands
makes provider requests or reads provider credentials.

## HTML and JUnit views

The report helpers accept one validated bundle or a sequence of bundles. A
sequence retains every supplied trial. An empty sequence produces an explicit
missing-evidence row rather than an empty successful test suite.

```python
from pathlib import Path
from pytest_wardenbot.agents.evidence_reports import (
    evidence_to_junit,
    render_evidence_html,
)

# bundle is a validated EvidenceBundle created or loaded through the core API.
Path("evidence.html").write_text(render_evidence_html(bundle), encoding="utf-8")
Path("evidence.xml").write_text(evidence_to_junit(bundle), encoding="utf-8")
```

The standalone HTML works offline, uses no external assets or scripts, and
escapes all recorded content. Its content security policy disables network
resources, scripts and form submission. It shows recorded security, task
utility, missing execution coverage, evidence provenance, grader and
fingerprints independently. Whether the sanitized report retains inputs for offline regrading is
shown separately: content omission can prevent regrading an otherwise completed
original trial.

JUnit emits two test cases per supplied trial: `.security` and `.utility`.
Test properties preserve the recorded outcome, utility, exposure, reason codes,
provenance, scenario identity, grader and fingerprints. A utility failure does
not relabel a resisted security outcome. Truncated retained event lists are
explicitly marked and cannot produce a required security pass.

| Recorded dimension | JUnit result |
| --- | --- |
| Observed violation | Failure |
| Infrastructure error | Error |
| Resistance with complete declared execution coverage | Pass |
| Task utility succeeded | Pass in its separate utility test |
| Task utility failed | Failure in its separate utility test |
| Inconclusive, unsupported, missing evidence, or unknown task utility | Error by default |

The default `required=True` requires both security and task utility coverage.
Use `evidence_to_junit(bundle, required=False)` to represent unavailable security
coverage and unknown utility as skipped tests. Neither mode turns missing
execution into a pass. These results describe saved evidence; generating JUnit
does not execute or regrade a trial. A missing campaign row must be included as
missing coverage by its integration; supplying a subset of completed bundles
cannot establish coverage of omitted campaign cases.

## Regrading and new execution

Offline regrading applies the deterministic grader to saved scenario and
observation snapshots. It makes no model or tool calls. It requires complete,
retained inputs and refuses bundles whose redaction, truncation or omitted
observations prevent reconstructing the original grading boundary. It checks
these saved observations, including their declared provenance; it cannot
independently authenticate a saved harness trace.

Fixture replay performs a new bounded execution of an explicitly supported
built-in fixture. Its manifest names a fixed, versioned fixture and assertions.
It does not execute arbitrary code, arbitrary URLs, shell commands, imported
classes or remediation text found in a payload. Inspecting, rendering,
comparing and offline regrading a bundle do not authorize replay.

A fresh application run requires the application-owned target, its instrumented
resources and an explicit execution request. A live model run can cost money
and produce different behavior even with matching declared configuration.
A fixture replay establishes the fixture mechanics; it does not reproduce a
production application or prove model robustness. Execution mode labels retain
the difference between recorded evidence, offline regrading, fixture execution
and fixture replay.

## Baseline comparison

A baseline comparison requires compatible scenario, corpus, target and
configuration fingerprints and a compatible grader. A mismatch is a refused
comparison with explicit reasons, not an improvement or regression. Reports
show baseline and current security outcomes and task utility independently.

```python
# comparison is produced by compare_evidence(baseline, current).
html = render_evidence_html(current, comparison=comparison)
xml = evidence_to_junit(current, comparison=comparison)
```

Matching fingerprints describe the declared configuration, not hidden provider
state or every source of nondeterminism. A pair of compatible trials cannot
establish causality, generalize to a model-wide score, or eliminate uncertainty
from limited samples. Report sample counts and missing coverage alongside any
observed change.

## Privacy and fingerprints

Content is hidden by default in bundles and reports. Explicit content capture
can retain prompts, canaries, tool arguments and private application data. To
show already retained content, pass an explicit `PrivacyPolicy` to the report;
it cannot recover content omitted when the bundle was created.

```python
from pytest_wardenbot.agents import PrivacyPolicy

policy = PrivacyPolicy(include_content=True, secrets=("known-private-value",))
html = render_evidence_html(bundle, policy=policy)
```

Configured literal secrets and sensitive keys are filtered before rendering;
unrecognized private information cannot be inferred automatically. Redaction
and truncation can deliberately make exact offline regrading unavailable.
Review captured artifacts before sharing them, and retain unredacted originals
only in an appropriate private location.

Fingerprints are identifiers, not encryption or anonymization. Low-entropy
inputs can sometimes be guessed and checked against a public hash. Keep
credentials out of structural labels and fingerprint inputs; configuration
fingerprints should describe safe declared settings rather than secret values.
A locally recomputed checksum also cannot authenticate evidence modified by
someone who can rewrite the artifact.
