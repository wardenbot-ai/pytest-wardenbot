# Evaluation: how the bundled suite performs against real bots

This page documents the methodology for evaluating the v0.1 deterministic
suite against named LLMs, plus result tables you (the reader) can fill in
by running the included scripts. There are no pre-baked numbers here —
the maintainers don't ship live model outputs in the repo because (a)
results drift quickly as vendors update models and (b) we want every
user to run the eval themselves so they trust the numbers they see.

## What the evaluation answers

Three questions:

1. **Does a frontier model with a well-written system prompt pass the
   suite out-of-the-box?** If yes, the suite is well-calibrated for
   well-behaved bots (low false-positive rate).
2. **Does the suite catch a deliberately-vulnerable bot?** If yes, the
   suite has real signal (low false-negative rate against obvious
   failures).
3. **Where does each model show the most behavior variance?** Useful
   when picking a model or sizing the risk of a planned migration.

## What the evaluation does NOT answer

- Whether the suite catches **novel** attacks. By definition no fixed
  corpus catches all novel attacks. The suite is a smoke test for known
  failure patterns + a regression detector for your specific bot.
- Whether one model is "safer" than another in production. The eval runs
  bare models with a fixed support-bot system prompt — your real
  deployment will have different prompts, different RAG, different tool
  use, all of which dominate the security posture.

## Setup

```bash
git clone https://github.com/pardamike/pytest-wardenbot.git
cd pytest-wardenbot
python -m venv .venv
source .venv/bin/activate
pip install -e ".[openai,anthropic,dev]"
pip install pytest-json-report python-dotenv  # eval-only conveniences
cp scripts/evaluation/.env.example scripts/evaluation/.env
$EDITOR scripts/evaluation/.env       # paste your API keys
python -m scripts.evaluation.run
```

The runner reads `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from
`scripts/evaluation/.env` (gitignored). It runs the bundled deterministic
suite against each configured bot and writes:

- `scripts/evaluation/results/<bot>.json` — machine-readable per-test
  outcomes.
- `scripts/evaluation/results/<bot>.md` — human-readable per-category
  pass/fail summary.
- `scripts/evaluation/results/SUMMARY.md` — comparison table across all
  configured bots.

Pre-baked entries in `SUMMARY.md` start blank — your run fills them in.

## Bots evaluated

| Bot ID | Backend | Purpose |
|---|---|---|
| `openai-gpt-4o-mini` | `openai` extra, `gpt-4o-mini` | Well-behaved frontier control |
| `anthropic-haiku-4-5` | `anthropic` extra, `claude-haiku-4-5` | Well-behaved frontier control |
| `vulnerable-stub` | local stub | Deliberately-vulnerable bot — must FAIL every category |

Add your own bots by editing `scripts/evaluation/bots.py` — see the
docstring for the contract.

## Result tables (fill in by running the eval)

Replace `—` with the actual pass count per category after running.

### openai-gpt-4o-mini

| Category | Expected | Observed |
|---|---|---|
| Prompt injection (10 tests) | 10 pass | — |
| System-prompt elicitation (3) | 3 pass | — |
| Refusal bypass (3) | 3 pass | — |
| Off-topic deflection (2) | 2 pass | — |
| Indirect injection / XPIA (4) | 4 pass | — |
| Encoded-payload (4) | 4 pass | — |
| Multi-turn jailbreak (3) | 3 pass | — |
| **Total deterministic** | **29 pass** | — |

### anthropic-haiku-4-5

| Category | Expected | Observed |
|---|---|---|
| Prompt injection (10 tests) | 10 pass | — |
| System-prompt elicitation (3) | 3 pass | — |
| Refusal bypass (3) | 3 pass | — |
| Off-topic deflection (2) | 2 pass | — |
| Indirect injection / XPIA (4) | 4 pass | — |
| Encoded-payload (4) | 4 pass | — |
| Multi-turn jailbreak (3) | 3 pass | — |
| **Total deterministic** | **29 pass** | — |

### vulnerable-stub

The stub is hand-crafted to **fail every category** so a passing eval
proves the test suite has signal:

| Category | Expected | Observed |
|---|---|---|
| Prompt injection (10 tests) | 10 fail | — |
| System-prompt elicitation (3) | 3 fail | — |
| Refusal bypass (3) | 3 fail | — |
| Off-topic deflection (2) | 2 fail | — |
| Indirect injection / XPIA (4) | 4 fail | — |
| Encoded-payload (4) | 4 fail | — |
| Multi-turn jailbreak (3) | 3 fail | — |
| **Total deterministic** | **29 fail** | — |

If the vulnerable stub passes any category, that category has a false
negative — file an issue.

## Cost

Per full eval run, against each frontier model:

| Bot | Calls | Tokens (~) | Cost (~USD) |
|---|---|---|---|
| openai-gpt-4o-mini | 29 single-turn + 3 multi-turn × 3 turns | ~25K | $0.05 |
| anthropic-haiku-4-5 | same | ~25K | $0.05 |

Multi-turn calls are ~3× the single-turn cost because each priming turn
plus the payload turn counts. Total per full run across both frontier
models: well under $1 at the time of this writing.

## Interpreting results

- **All frontier models pass everything:** great — the suite is
  well-calibrated. Confidence in passing-as-meaningful is high.
- **A frontier model fails some categories:** worth investigating. Either
  (a) the bot really is vulnerable to that pattern (publishable finding!),
  (b) the system prompt used in this eval is weaker than the production
  one, or (c) the test corpus has false positives in that category.
- **The vulnerable stub passes some categories:** the suite has a false
  negative in that category — the stub is supposed to fail. File an
  issue with the stub's response and the test that should have caught it.

## Methodology notes

- All bots receive the same support-bot-style system prompt (defined in
  `scripts/evaluation/system_prompts.py`). This isolates the model's
  behavior from the system-prompt variable.
- Temperature is fixed at 0 for reproducibility.
- Each evaluation run uses the bundled v0.1 corpus. If you've overridden
  any `wardenbot_*_prompts` fixtures, the eval still uses the bundled
  defaults (the eval has its own conftest, separate from your project's).
- Multi-turn tests use the adapter's `session_id` parameter to maintain
  state across turns. Bots whose adapters ignore `session_id` will
  produce artificially-high pass rates on multi-turn (each turn is
  effectively fresh).
