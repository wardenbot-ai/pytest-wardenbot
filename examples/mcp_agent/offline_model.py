"""A deterministic model simulator behind the real SDK HTTP transport.

This simulator establishes tool-loop mechanics, never model robustness.
"""

from __future__ import annotations

import importlib
import json
import re
from typing import Any

from openai import AsyncOpenAI, DefaultHttpxClient  # type: ignore[import-not-found]


def sdk_http_module() -> Any:
    """Use the HTTP generation selected by the installed official SDK."""
    for base in DefaultHttpxClient.__mro__:
        module = base.__module__.split(".")[0]
        if module in {"httpx", "httpx2"}:
            return importlib.import_module(module)
    raise RuntimeError("The installed OpenAI SDK uses an unsupported HTTP transport")


class OfflineModel:
    """Respond from actual HTTP request input, tools, and previous tool outputs."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.http = sdk_http_module()

    def respond(self, request: Any) -> Any:
        if request.url.host != "offline-agent.invalid" or request.url.path != "/v1/responses":
            raise RuntimeError("The offline simulator received an unexpected endpoint")
        data = json.loads(request.content)
        self.requests.append(data)
        outputs = [item for item in data["input"] if item.get("type") == "function_call_output"]
        tool_names = {tool["name"] for tool in data["tools"]}
        number = len(self.requests)
        text = "\n".join(str(item.get("content", item.get("output", ""))) for item in data["input"])
        directive = re.search(r"call (\S+) with arguments (\{[^\n]+)", text, re.IGNORECASE)
        if not outputs:
            output = self._call(number, "fetch_document", {})
        elif directive is not None and directive[1] in tool_names and len(outputs) == 1:
            arguments, _ = json.JSONDecoder().raw_decode(directive[2])
            output = self._call(number, directive[1], arguments)
        else:
            document = outputs[0]["output"]
            fact = re.search(r"\b\d+%|\b\d+ minutes", document)
            answer = "Document summary: " + (fact[0] if fact else "no factual answer")
            output = {
                "id": f"msg_offline_{number}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": answer, "annotations": []}],
            }
        body = {
            "id": f"resp_offline_{number}",
            "object": "response",
            "created_at": 1,
            "model": "offline-response-model",
            "status": "completed",
            "error": None,
            "incomplete_details": None,
            "output": [output],
            "usage": {
                "input_tokens": 40,
                "output_tokens": 12,
                "total_tokens": 52,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        return self.http.Response(200, json=body, request=request)

    @staticmethod
    def _call(number: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"fc_offline_{number}",
            "type": "function_call",
            "status": "completed",
            "call_id": f"call_offline_{number}",
            "name": name,
            "arguments": json.dumps(arguments),
        }

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="offline-synthetic-value",  # pragma: allowlist secret
            base_url="https://offline-agent.invalid/v1",
            max_retries=0,
            http_client=self.http.AsyncClient(transport=self.http.MockTransport(self.respond)),
        )
