# Design principles

The reasoning behind why pytest-wardenbot is shaped the way it is.

## 1. Script-first, LLM-fallback

Deterministic checks come before LLM-as-judge checks. Reasons:

- **Cost.** LLM calls are 1000–10,000× more expensive than a regex match.
- **Latency.** A regex returns in microseconds; an LLM call takes seconds.
- **Reproducibility.** A regex gives the same answer every time; an LLM
  judge gives ~80% agreement with itself across runs.
- **Auditability.** A regex match is easy to explain; an LLM verdict is
  not.
- **Cost-margin economics.** If we ever moved the test corpus to a paid
  managed service at $29/mo, deterministic-only checks make that price
  point viable. Judge-heavy designs do not.

What this means in practice: every shipped test grades with deterministic
checks first. The LLM-judge tests are an explicit opt-in (`[judge]` extra),
reserved for checks no deterministic rule can express (semantic equivalence,
brand voice, hallucination grounding).

## 2. Conservative detection patterns

When designing a regex / substring detector, false positives cost more
trust than false negatives.

- A false positive ("your bot leaked the system prompt!" when it actually
  said "I help with billing questions") makes users distrust the entire
  suite.
- A false negative (a real leak we missed) is recoverable when discovered.

So we err on the side of missing specific variants rather than firing on
non-issues. This explicit bias is documented in the comments next to each
pattern list.

## 3. Plain `pytest` integration, not a parallel framework

The whole tool is a `pytest11` entry-point plugin. No custom test runner,
no custom report format, no custom CI integration. If you have pytest in
your stack, you have wardenbot.

This matters because:

- You don't learn a new tool.
- Your existing CI works unchanged.
- Your `pytest.ini` / `pyproject.toml` settings apply.
- Your `pytest-xdist`, `pytest-cov`, `pytest-rerunfailures` all work.

## 4. Honest failure messages with agent-ready remediation

Every failure message includes a structured Markdown block labeled
`Agent-ready remediation (paste into Cursor / Claude Code)`. The block is
not just description — it's a complete instruction-set the AI assistant
in your IDE can act on.

This is a 2026-native pattern. Most security tools ship PDFs you read.
We ship instructions for the agent that will fix the problem.

## 5. The OSS plugin is the funnel, not the product

The plugin is intentionally scoped to *local pytest runs* and *CI*. The
things that need a backend — cross-run history, scheduled monitoring,
behavior-diff alerts on regression, the Bot Health Score composite — live
in the managed [WardenBot AI](https://wardenbot.ai) service.

This split is explicit so we don't accept PRs that drift the plugin into
"a small version of the managed service." If your idea is in the second
bucket, the right home is the managed-service waitlist.

This also means:

- The OSS plugin will never gain a managed-service mode that secretly
  uploads your data somewhere.
- Apache 2.0, forever. No license rugpulls.
- No telemetry by default.

## 6. Honest reliability disclosure

The LLM-judge tests use Anthropic Haiku 4.5 by default. Per published
research, single LLM judges agree with human raters about 80% of the
time on safety/quality scoring. We say this explicitly in the docs, in
the judge module docstring, and in failure messages.

The alternative — selling LLM-judge as if it were 100% reliable — would
be dishonest and would break user trust the first time the judge got it
wrong on a high-stakes call.

## 7. Maintainer commitments

- **Semver.** Major bumps come with 6-month deprecation warnings.
- **No surprise license changes.** The license is in `LICENSE.md`. It's
  Apache 2.0. It will stay Apache 2.0.
- **No telemetry without opt-in.** If we ever add opt-in telemetry, the
  data shape will be documented and the opt-in will be explicit (not a
  buried setting).
- **Monthly minor releases** on the second Tuesday of the month.
- **Triage rule.** Anything the managed service does is out-of-scope for
  the plugin. PRs that try to add it will be politely declined with the
  rationale documented above.
