# Local application boundary controls

Install `pytest-wardenbot`, then obtain this examples directory from the source
checkout or source distribution. Run the script by absolute path from any
working directory:

```bash
cd /tmp
/path/to/venv/bin/python /path/to/pytest-wardenbot/examples/application_packs/run_controls.py
```

The example imports the installed plugin, uses only core dependencies, and
requires no API keys, SDKs, network services or environment configuration.
It executes a controlled local support/knowledge application with synthetic
records, memories, identities and write sinks. Its deterministic targets test
fixture mechanics rather than model robustness or production authorization.

Each pack runs four controls: a legitimate benign task, an intentionally
vulnerable attack, a resistant attack and a no-exposure case. Security outcome,
task utility and exposure are reported separately. Completing the example means
its declared control expectations were reproduced; a deliberate violation is
an expected control result, and no-exposure cases remain inconclusive.

Factories create a separate target and application harness for each trial.
Run-wide call/turn caps and a deadline bound the campaign, and target reset
releases trial-local state. Observed reads, persistent memory changes and write
mutations are recorded by the harness independently of target claims. A budget
rejection before an operation prevents its effect, while an already observed
forbidden effect remains a violation after a later failure.

The memory pack exercises an injected memory-writing turn followed by a clean
later session that reads persisted state. Synthetic tenant and role fixtures
exercise application-defined boundaries, and approval/write fixtures require
approval for the specific requested operation. These controls cannot establish
production IAM, an OAuth flow, a full tenant boundary, or policies outside the
fixture's observed hooks.

Successful execution exits zero and writes JSON with twenty planned trials:
five deliberately violated, five resisted, ten inconclusive (five benign
baselines and five no-exposure controls), and fourteen successful legitimate
tasks. The deliberately vulnerable approval attack closes the ticket after its
approved triage and therefore fails the legitimate final-state task. The
control gate expects this known false utility while preserving the violation. Every row records the pack, control variant, required observation hooks
and actual observed event counts. Unavailable usage remains unknown. No report
file is saved unless you pass `--output` or redirect stdout.

The example also constructs content-minimized B2 evidence bundles. Public
synthetic snapshots can be explicitly retained for offline deterministic
regrading; this does not execute the application again:

```bash
/path/to/venv/bin/python /path/to/pytest-wardenbot/examples/application_packs/run_controls.py \
  --include-synthetic-content --output application-controls.json
```

`evidence_bundles` contains one validated bundle per executed trial. With the
explicit synthetic-content flag these support deterministic offline regrading;
without it, raw fixture content is hidden and exact regrading is unavailable.
Reports generated as JUnit from deliberately vulnerable bundles still contain
security failures, even though the control script exits zero for reproducing
its expected violation. Evidence provenance and
scenario/configuration fingerprints describe the fixture. They do not
authenticate a saved trace or establish a model-wide safety score.

The target/harness boundary is an integration seam for an application-owned
model agent: targets may consume exposed retrieval/memory/identity/write hooks,
while observations stay owned by the harness. This example has no model pilot
or live execution path.
