"""A scripted LangChain chat model with real tool binding, for offline graph tests.

It uses the same decisions as ``scripted_chat_model.chat_completion``: fetch
the document first, obey the harness's synthetic instruction when
``behavior="vulnerable"``, otherwise answer with the document's fact. It
establishes graph mechanics, never model robustness.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel  # type: ignore[import-not-found]
from langchain_core.messages import AIMessage, BaseMessage  # type: ignore[import-not-found]
from langchain_core.outputs import ChatGeneration, ChatResult  # type: ignore[import-not-found]
from langchain_core.utils.function_calling import convert_to_openai_tool  # type: ignore[import-not-found]

from tests.fixtures.scripted_chat_model import chat_completion


def _openai_message(message: BaseMessage) -> dict[str, Any]:
    role = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}.get(
        message.type, message.type
    )
    data: dict[str, Any] = {"role": role, "content": message.text}
    if isinstance(message, AIMessage) and message.tool_calls:
        data["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
            }
            for call in message.tool_calls
        ]
    return data


class ScriptedToolModel(BaseChatModel):
    behavior: str = "resistant"
    calls: int = 0
    malformed: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted-tool-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self.bind(tools=[convert_to_openai_tool(tool) for tool in tools], **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls += 1
        payload = {
            "model": "scripted",
            "messages": [_openai_message(message) for message in messages],
            "tools": kwargs.get("tools") or [],
        }
        status, body = chat_completion(payload, self.behavior, self.calls)
        if status != 200:
            raise ValueError(f"Error code: {status} - {body['error']['message']}")
        reply = body["choices"][0]["message"]
        tool_calls = []
        invalid = []
        for call in reply.get("tool_calls") or ():
            arguments = call["function"]["arguments"]
            if self.malformed and call["function"]["name"] != "fetch_document":
                invalid.append(
                    {
                        "name": call["function"]["name"],
                        "args": arguments[:-1],
                        "id": call["id"],
                        "error": "bad json",
                        "type": "invalid_tool_call",
                    }
                )
                continue
            tool_calls.append(
                {"name": call["function"]["name"], "args": json.loads(arguments), "id": call["id"]}
            )
        message = AIMessage(
            content=reply.get("content") or "",
            tool_calls=tool_calls,
            invalid_tool_calls=invalid,
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])
