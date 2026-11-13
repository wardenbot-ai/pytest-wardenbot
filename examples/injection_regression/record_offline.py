"""Write the example's hash-matched recording with record mode, against a local stand-in.

A real project runs record mode against the real API:

    WARDENBOT_MODEL_MODE=record OPENAI_API_KEY=... pytest source_rating -k hash

This script does the same against a local server that answers like the API,
so the committed recording needs no key: python record_offline.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BENIGN = json.loads((HERE / "llm_responses" / "source_rating" / "benign_batch.json").read_text())


class StandIn(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        reply = {
            "id": "chatcmpl-example",
            "object": "chat.completion",
            "created": 1763000000,
            "model": "gpt-4.1-mini-2025-04-14",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(BENIGN)},
                }
            ],
            "usage": {"prompt_tokens": 180, "completion_tokens": 60, "total_tokens": 240},
        }
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        pass


def main() -> None:
    # WARDENBOT_* variables outrank install()'s arguments (so record mode can be
    # switched on without editing code); clear them so this always records here.
    for name in [name for name in os.environ if name.startswith("WARDENBOT_")]:
        del os.environ[name]
    server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}/v1"
        os.environ["OPENAI_API_KEY"] = "offline-stand-in"  # pragma: allowlist secret
        os.chdir(HERE)
        sys.path.insert(0, str(HERE))

        from pytest_wardenbot.model import install, model_endpoint

        endpoint = install(mode="record", responses_dir=HERE / "llm_responses")
        assert endpoint.mode == "record", endpoint.mode
        from source_rating import fixed
        from source_rating.test_source_rating import attack_text, sources

        with model_endpoint("source_rating_hash_churn"):
            fixed.rate_sources(sources(attack_text("source_rating_hash_churn")))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
