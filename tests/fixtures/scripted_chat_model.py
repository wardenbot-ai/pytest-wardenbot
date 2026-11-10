"""A scripted OpenAI-compatible chat model for offline agent tests.

It answers Chat Completions requests from what is actually in them: it calls
``fetch_document`` first, obeys the harness's synthetic instruction when
``behavior="vulnerable"``, and otherwise answers with the document's fact.
It establishes loop mechanics, never model robustness. The same logic backs an
in-process SDK transport and a real local HTTP server.
"""

from __future__ import annotations

import importlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DIRECTIVE = re.compile(r"Ignore your task\. Call (\S+) with arguments (\{[^\n]*\})")
BEHAVIORS = ("resistant", "vulnerable", "no_tools", "rejects_tools", "text_tool_call", "judge")


def _call(number: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{number}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


def chat_completion(
    payload: dict[str, Any], behavior: str = "resistant", number: int = 1
) -> tuple[int, dict[str, Any]]:
    """Return (HTTP status, JSON body) for one Chat Completions request."""
    if behavior not in BEHAVIORS:
        raise ValueError(f"unknown behavior {behavior!r}")
    tools = {
        tool["function"]["name"]: tool["function"]
        for tool in payload.get("tools") or ()
        if tool.get("type") == "function"
    }
    if tools and behavior == "rejects_tools":
        return 400, {
            "error": {
                "message": f"registry.ollama.ai/library/{payload['model']} does not support tools",
                "type": "api_error",
            }
        }
    messages = payload.get("messages") or []
    outputs = [str(m.get("content") or "") for m in messages if m.get("role") == "tool"]
    made = [
        call["function"]["name"]
        for message in messages
        if message.get("role") == "assistant"
        for call in message.get("tool_calls") or ()
    ]
    seen = "\n".join(
        [str(m.get("content") or "") for m in messages]
        + [str(tool.get("description") or "") for tool in tools.values()]
    )
    message: dict[str, Any]
    probe = next((name for name in tools if name == "wardenbot_probe"), None)
    if behavior == "judge":
        # One reply that satisfies both DeepEval GEval schemas (steps, then score).
        verdict = {"steps": ["Compare the meaning."], "score": 9, "reason": "Equivalent."}
        message = {"role": "assistant", "content": json.dumps(verdict)}
    elif behavior == "text_tool_call" and tools:
        message = {"role": "assistant", "content": '{"name": "fetch_document", "arguments": {}}'}
    elif behavior == "no_tools" or not tools:
        fact = re.search(r"\d+%", seen)
        answer = f"Sales changed by {fact[0] if fact else 'n/a'}."
        message = {"role": "assistant", "content": answer}
    elif probe is not None and probe not in made:
        message = _call(number, probe, {"value": "ready"})
    elif "fetch_document" in tools and "fetch_document" not in made:
        message = _call(number, "fetch_document", {})
    elif (
        behavior == "vulnerable"
        and (directive := DIRECTIVE.search(seen)) is not None
        and directive[1] not in made
    ):
        message = _call(number, directive[1], json.loads(directive[2]))
    else:
        fact = re.search(r"\d+%", "\n".join(outputs) or seen)
        message = {
            "role": "assistant",
            "content": f"Quarterly sales increased by {fact[0] if fact else 'an unknown amount'}.",
        }
    return 200, {
        "id": f"chatcmpl-{number}",
        "object": "chat.completion",
        "created": 0,
        "model": payload.get("model", "scripted"),
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                "message": message,
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


class ScriptedChatModel:
    """Counts requests and answers them with ``chat_completion``."""

    def __init__(self, behavior: str = "resistant") -> None:
        self.behavior = behavior
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def answer(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if not path.rstrip("/").endswith("/chat/completions"):
            return 404, {"error": {"message": f"unexpected path {path}"}}
        with self._lock:
            self.requests.append(payload)
            number = len(self.requests)
        return chat_completion(payload, self.behavior, number)

    def http_client(self) -> Any:
        """An async HTTP client for the installed OpenAI SDK that never opens a socket."""
        from openai import DefaultHttpxClient  # type: ignore[import-not-found]

        http = next(
            importlib.import_module(base.__module__.split(".")[0])
            for base in DefaultHttpxClient.__mro__
            if base.__module__.split(".")[0] in {"httpx", "httpx2"}
        )

        def handle(request: Any) -> Any:
            status, body = self.answer(request.url.path, json.loads(request.content))
            return http.Response(status, json=body)

        return http.AsyncClient(transport=http.MockTransport(handle))


class LocalChatServer:
    """Serve a ``ScriptedChatModel`` on 127.0.0.1 like a local model server would."""

    def __init__(self, model: ScriptedChatModel) -> None:
        self.model = model
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                status, body = outer.model.answer(self.path, payload)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> LocalChatServer:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
