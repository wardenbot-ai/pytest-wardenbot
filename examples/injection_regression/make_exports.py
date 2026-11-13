"""Build llm_responses/exports/posts.jsonl from the hand-written replies.

This is the export shape a project would produce from its own logs: one line
per model call, with the request the application sent, the response it got,
and the case it belongs to. Headers are never exported. The request is what
the fixed version sends today; replay picks entries by case (the manifest's
where rules), so after editing the prompt, regenerate the file to keep it an
honest log.

    python make_exports.py          # write the file
    python make_exports.py --check  # exit 1 if the file is out of date
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FOLDER = HERE / "llm_responses"
EXPORT = FOLDER / "exports" / "posts.jsonl"
CASES = {
    "post_summary_attack": FOLDER / "post_summary" / "attack.json",
    "post_summary_benign": FOLDER / "post_summary" / "benign.json",
}


def build() -> str:
    # WARDENBOT_* variables outrank install()'s arguments; clear them so the
    # markers always come from the folder's seed, the same on every machine.
    for name in [name for name in os.environ if name.startswith("WARDENBOT_")]:
        del os.environ[name]
    sys.path.insert(0, str(HERE))
    from pytest_wardenbot.model import injection_marker, install

    endpoint = install(mode="replay", responses_dir=FOLDER)
    assert endpoint.mode == "replay", endpoint.mode
    from llm import MODEL
    from post_summary import data, fixed

    lines = []
    for case, reply_file in CASES.items():
        reply = json.loads(reply_file.read_text(encoding="utf-8"))
        posts = (
            data.benign_posts() if case.endswith("benign") else data.posts(injection_marker(case))
        )
        request = {
            "model": MODEL,
            "messages": fixed.messages(posts),
            "response_format": {"type": "json_object"},
        }
        response = {
            "id": f"chatcmpl-{case}",
            "object": "chat.completion",
            "created": 1763000000,
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(reply)},
                }
            ],
            "usage": {"prompt_tokens": 210, "completion_tokens": 40, "total_tokens": 250},
        }
        record = {
            "case": case,
            "path": "/v1/chat/completions",
            "request": request,
            "response": response,
        }
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return "\n".join(lines) + "\n"


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        current = EXPORT.read_text(encoding="utf-8") if EXPORT.exists() else ""
        if current != text:
            print(f"{EXPORT} is out of date: run python make_exports.py")  # noqa: T201
            return 1
        return 0
    EXPORT.parent.mkdir(parents=True, exist_ok=True)
    EXPORT.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
