# Portable finding controls

Install the core wheel, obtain this example from the source archive or checkout,
and run it from any working directory. No optional SDKs or API keys are needed.

```bash
python /path/to/pytest-wardenbot/examples/evidence/run_controls.py --output-dir ./evidence-demo
```

Open `evidence-demo/finding.html`. The directory also contains versioned JSON,
JUnit, a validated copy, an offline re-grade, and a new execution of the bound
synthetic fixture. The example includes only the fixture's fixed public content.
It executes the CLI in separate Python processes from the output directory,
without adding checkout source paths.

The known-vulnerable control must reproduce an observed violation. Consequently
its JUnit file contains a failure and `regrade` exits 1. The example itself exits
0 when those expected findings and the portable fixture replay are verified.
`replay` exits 0 when the expected control assertion reproduces; it does not mean
that the target resisted an attack. `inspect` and `compare` are descriptive
commands, not security gates. Incomplete re-grades exit 2.

To work with an exported bundle directly:

```bash
python -m pytest_wardenbot.agents.evidence_cli inspect finding.json --html finding.html
python -m pytest_wardenbot.agents.evidence_cli regrade finding.json --output grade.json
python -m pytest_wardenbot.agents.evidence_cli replay finding.json --output rerun.json
python -m pytest_wardenbot.agents.evidence_cli compare finding.json rerun.json --html comparison.html
```

`regrade` uses saved observations without running a target. Default content-minimized
exports lack the raw assertion inputs needed for an exact grade. `replay` supports
only the built-in synthetic fixture manifest; it cannot execute an arbitrary app,
script, URL or model named in a bundle. A new live run uses your application's own
instrumented integration and may produce different results.

Fingerprints help detect changes, but neither hashes nor stored provenance labels
authenticate an artifact. Review an artifact's origin and any opted-in content
before sharing it. See the [evidence guide](../../docs/how-to/evidence-bundles.md).
