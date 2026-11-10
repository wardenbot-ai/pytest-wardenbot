"""Collect chatbot responses for the grading probe set.

Sends the shipped refusal-bypass, off-topic and system-prompt-elicitation
prompts to each model under each system prompt in
`tests/fixtures/grading_probes.json`, and appends unlabeled rows to a JSONL
file. Label new rows by reading them, before running the graders, then add
them to the probe file (see docs/reference/grading-accuracy.md).

Models are given as `provider:name`:

- `ollama:<model>` uses a local Ollama server (OpenAI-compatible API on
  localhost:11434). No API key needed.
- `openai:<model>` reads `OPENAI_API_KEY` from the environment.
- `anthropic:<model>` reads `ANTHROPIC_API_KEY` from the environment.

Example:

    python scripts/evaluation/collect_grading_probes.py out.jsonl \\
        --system-prompt acme-strict --system-prompt northwind-bank \\
        ollama:qwen2.5:7b ollama:mistral:7b

OpenAI-compatible and Ollama models run at temperature 0. Current Anthropic
models do not accept a temperature, so they run at their default.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from pytest_wardenbot.corpus.off_topic import OFF_TOPIC_PROMPTS
from pytest_wardenbot.corpus.refusal_bypass import REFUSAL_BYPASS_PROMPTS
from pytest_wardenbot.corpus.system_prompt_leak import SYSTEM_PROMPT_LEAK_PROMPTS

PROBES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "grading_probes.json"
PROMPTS = (
    [("refusal_bypass", p, a) for p, a in REFUSAL_BYPASS_PROMPTS]
    + [("off_topic", p, a) for p, a in OFF_TOPIC_PROMPTS]
    + [("system_prompt_leak", p, a) for p, a in SYSTEM_PROMPT_LEAK_PROMPTS]
)


def ask(model: str, system: str, user: str, *, max_tokens: int = 700) -> str:
    provider, _, name = model.partition(":")
    if provider in {"ollama", "openai"}:
        openai = importlib.import_module("openai")
        if provider == "ollama":
            # Ollama ignores the key, but the client requires one.
            placeholder = "ollama"  # pragma: allowlist secret
            client = openai.OpenAI(base_url="http://localhost:11434/v1", api_key=placeholder)
        else:
            client = openai.OpenAI()
        out = client.chat.completions.create(
            model=name,
            temperature=0,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return out.choices[0].message.content or ""
    if provider == "anthropic":
        anthropic = importlib.import_module("anthropic")
        reply = anthropic.Anthropic().messages.create(
            model=name,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in reply.content if getattr(b, "type", "") == "text")
    raise SystemExit(f"unknown provider in {model!r}; use ollama:, openai: or anthropic:")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect chatbot responses for the probe set.")
    parser.add_argument("out", type=Path, help="JSONL file to append to (resumable)")
    parser.add_argument("models", nargs="+", help="provider:model, e.g. ollama:qwen2.5:7b")
    parser.add_argument(
        "--system-prompt",
        action="append",
        dest="system_prompts",
        help="system prompt name from the probe file (repeatable; default: all)",
    )
    args = parser.parse_args(argv)

    available = json.loads(PROBES.read_text(encoding="utf-8"))["system_prompts"]
    names = args.system_prompts or sorted(available)
    unknown = sorted(set(names) - set(available))
    if unknown:
        parser.error(f"unknown system prompt(s): {unknown}; known: {sorted(available)}")

    done: set[tuple[str, str, str]] = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done.add((row["source"], row["system_prompt"], row["prompt_id"]))

    with args.out.open("a", encoding="utf-8") as fh:
        for model in args.models:
            for name in names:
                for test, prompt, prompt_id in PROMPTS:
                    if (model, name, prompt_id) in done:
                        continue
                    try:
                        text = ask(model, available[name], prompt)
                    except Exception as exc:  # report the class only; never echo keys
                        print(f"{model} {name} {prompt_id}: {type(exc).__name__}", file=sys.stderr)
                        continue
                    row = {
                        "test": test,
                        "source": model,
                        "system_prompt": name,
                        "prompt_id": prompt_id,
                        "text": text,
                    }
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(f"{model} {name} {prompt_id}: {len(text)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
