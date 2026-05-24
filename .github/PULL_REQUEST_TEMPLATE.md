<!-- Thanks for the contribution! -->

## What does this PR do?

<!-- 1-3 sentences. Link any issue this closes (Closes #N). -->

## Scope check

<!-- Confirm the change fits the OSS plugin's scope. See CONTRIBUTING.md -->

- [ ] This change does NOT add managed-service features (history / alerting / dashboards / scheduling).
- [ ] If this adds a new shipped test or probe, it's deterministic (regex / substring / schema) where possible.
- [ ] If this changes public API, it's backwards-compatible OR documented as a breaking change in the description.

## Tests + lint

- [ ] `pre-commit run --all-files` passes locally
- [ ] `coverage run -m pytest && coverage report` passes locally (≥80%)
- [ ] If this adds a new shipped test, the test passes against a safe mock AND fails against a vulnerable mock (covered in `tests/test_plugin.py`)

## Notes for reviewers

<!-- Anything subtle? Trade-offs you made? -->
