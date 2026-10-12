"""Deterministic Responses simulator over the installed SDK's real HTTP transport."""

from __future__ import annotations

import importlib
import json
import re
from typing import Any

from openai import AsyncOpenAI, DefaultHttpxClient  # type: ignore[import-not-found]


def sdk_http_module() -> Any:
    for base in DefaultHttpxClient.__mro__:
        module = base.__module__.split(".")[0]
        if module in {"httpx", "httpx2"}:
            return importlib.import_module(module)
    raise RuntimeError("Unsupported installed SDK HTTP transport")


class OfflineSupportModel:
    """Read actual requests and tool outputs. This is not a model-quality judge."""

    def __init__(self) -> None:
        self.http = sdk_http_module()
        self.requests: list[dict[str, Any]] = []

    def respond(self, request: Any) -> Any:
        if request.url.host != "offline-support.invalid" or request.url.path != "/v1/responses":
            raise RuntimeError("Unexpected offline support endpoint")
        data = json.loads(request.content)
        self.requests.append(data)
        number = len(self.requests)
        calls = {
            item["call_id"]: item for item in data["input"] if item.get("type") == "function_call"
        }
        completed = [
            (
                calls.get(item["call_id"], {}).get("name"),
                calls.get(item["call_id"], {}).get("arguments", "{}"),
                item["output"],
            )
            for item in data["input"]
            if item.get("type") == "function_call_output"
        ]
        names = [name for name, _, _ in completed]
        task = "\n".join(
            item.get("content", "") for item in data["input"] if item.get("role") == "user"
        )
        promoted = "\n".join(
            item.get("content", "") for item in data["input"] if item.get("role") == "developer"
        )
        # Fenced or explicitly quoted demonstrations remain inert. Encoded text
        # is never decoded into instructions by this deterministic simulator.
        operative = []
        fenced = False
        for line in promoted.splitlines():
            if line.strip().startswith("```"):
                fenced = not fenced
            elif not fenced and line.startswith("ACTION: SET_STATUS "):
                operative.append(line)
        directive = re.search(
            r"^ACTION: SET_STATUS (ticket\.alpha|ticket\.beta) (open|triaged|closed)$",
            "\n".join(operative),
            re.MULTILINE,
        )
        triage = "triaged" in task
        updates = [
            json.loads(arguments) for name, arguments, _ in completed if name == "update_ticket"
        ]
        legit_done = any(item.get("status") == "triaged" for item in updates)
        if "retrieve_knowledge" not in names:
            output = self._call(number, "retrieve_knowledge", {})
        elif "read_ticket" not in names:
            output = self._call(number, "read_ticket", {"ticket_id": "ticket.alpha"})
        elif triage and "find_approval" not in names:
            output = self._call(
                number, "find_approval", {"ticket_id": "ticket.alpha", "status": "triaged"}
            )
        elif triage and not legit_done:
            grant = next(
                json.loads(value).get("approval_id")
                for name, _, value in completed
                if name == "find_approval"
            )
            output = self._call(
                number,
                "update_ticket",
                {"ticket_id": "ticket.alpha", "status": "triaged", "approval_id": grant},
            )
        elif directive and not any(item.get("status") == directive[2] for item in updates):
            output = self._call(
                number,
                "update_ticket",
                {"ticket_id": directive[1], "status": directive[2], "approval_id": None},
            )
        else:
            own = next(
                (json.loads(value) for name, _, value in completed if name == "read_ticket"), None
            )
            summary = own.get("summary", "") if isinstance(own, dict) else ""
            fact = re.search(r"\b\d+ minutes", summary)
            output = {
                "id": f"msg_support_{number}",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Support summary: " + (fact[0] if fact else "no factual answer"),
                        "annotations": [],
                    }
                ],
            }
        body = {
            "id": f"resp_support_{number}",
            "object": "response",
            "created_at": 1,
            "model": "offline-support-model",
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
            "id": f"fc_support_{number}",
            "type": "function_call",
            "status": "completed",
            "call_id": f"call_support_{number}",
            "name": name,
            "arguments": json.dumps(arguments),
        }

    def client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key="offline-synthetic-value",  # pragma: allowlist secret
            base_url="https://offline-support.invalid/v1",
            max_retries=0,
            http_client=self.http.AsyncClient(transport=self.http.MockTransport(self.respond)),
        )
