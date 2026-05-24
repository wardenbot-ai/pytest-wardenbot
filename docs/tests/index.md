# Test catalog

`pytest-wardenbot` v0.1 ships **30 deterministic tests** out of the box,
plus an opt-in canary-token leak test, plus user-parametrized business-truth
and LLM-judge tests. All discoverable via
`pytest --pyargs pytest_wardenbot.tests`.

## At a glance

| Category | Count | Grading | API key needed? |
|---|---|---|---|
| [Prompt injection](prompt-injection.md) | 5 prompts × 2 checks = 10 | deterministic | no |
| [System-prompt elicitation](system-prompt-leak.md) | 3 | deterministic | no |
| [Refusal bypass](refusal-bypass.md) | 3 | deterministic | no |
| [Off-topic deflection](off-topic.md) | 2 | deterministic | no |
| Indirect / cross-prompt injection (XPIA) | 4 | deterministic | no |
| Encoded-payload jailbreak (Base64 / ROT13 / leet / hex) | 4 | deterministic | no |
| Multi-turn jailbreak (priming + payload) | 3 | deterministic | no |
| Canary-token leak (opt-in; you plant the token) | 1 | deterministic | no |
| [Business truth](business-truth.md) | user-supplied | deterministic | no |
| [LLM-judge (semantic)](semantic.md) | user-supplied | LLM-judge | yes, with `[judge]` extra |

## What "passing" means (and doesn't)

A green run means your chatbot didn't fail any of the bundled 30 attacks
in the most overt way. It's a useful smoke test and a regression detector
— if a deploy turns a green test red, that's a real signal to investigate.

A green run does **not** mean your chatbot is secure. Frontier-grade
attacks are multi-turn, novel, and adapted to your specific bot — no fixed
corpus catches all of them. Treat the shipped suite as a starter set, not
a security audit.

## How the suite is graded

Per the WardenBot AI doctrine, every test is graded by the cheapest layer
that can produce a reliable signal:

1. **Deterministic** — regex, substring, schema. Zero LLM cost, fully
   reproducible. Catches roughly two-thirds of common failure modes.
2. **LLM-as-judge** (optional `[judge]` extra) — for subjective checks that
   no deterministic rule can express (brand voice, semantic equivalence,
   hallucination grounding).
3. **Human sampling** — not in v0.1 (lives in the managed [WardenBot AI](https://wardenbot.ai)
   service, not the OSS plugin).

## How failures are reported

Every failure message includes:

- The prompt that was sent
- The chatbot's response (truncated to 500 chars)
- Which detection patterns matched
- An **agent-ready remediation block** — paste it into Cursor / Claude Code
  to get a fix proposal

## What's NOT in the OSS plugin

Reserved for the managed [WardenBot AI](https://wardenbot.ai) service:

- Cross-run history / regression detection across deploys
- Daily / hourly scheduled runs against your bot
- Slack / webhook / email alerts on failure
- The "Bot Health Score" composite (0–100) and behavior-diff alerts
- Adversarial-agent attacker that adapts based on responses
- Canary phrase monitoring at managed scale

The plugin handles the local-developer + CI use cases. The managed service
handles the always-on monitoring use case.
