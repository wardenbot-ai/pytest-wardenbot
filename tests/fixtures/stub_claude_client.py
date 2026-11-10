"""A stand-in for ``ClaudeSDKClient`` that plays Claude Code offline.

It reads the trial's real options: it reports the configured tools in its
startup message, runs the configured ``PreToolUse`` hooks, calls tools through
the real in-process SDK MCP server (so the SDK's own argument validation
applies), honors ``max_turns``, and decides what to do with the same scripted
logic as the other offline models. It establishes target mechanics, never
model robustness.
"""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk import (  # type: ignore[import-not-found]
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)
from mcp import Client  # type: ignore[import-not-found]

from tests.fixtures.scripted_chat_model import chat_completion

PREFIX = "mcp__wardenbot__"


class StubClaudeClient:
    def __init__(
        self,
        options: Any,
        *,
        behavior: str = "resistant",
        extra_tools: tuple[str, ...] = (),
        deny: frozenset[str] = frozenset(),
        corrupt_arguments: bool = False,
        fail: bool = False,
    ) -> None:
        self.options = options
        self.behavior = behavior
        self.extra_tools = extra_tools
        self.deny = deny
        self.corrupt_arguments = corrupt_arguments
        self.fail = fail
        self.prompt = ""
        self.hook_calls: list[str] = []

    async def __aenter__(self) -> StubClaudeClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def query(self, prompt: str) -> None:
        self.prompt = prompt

    async def _hooks(self, name: str, arguments: dict[str, Any], tool_use_id: str) -> None:
        for matcher in (self.options.hooks or {}).get("PreToolUse", []):
            for hook in matcher.hooks:
                self.hook_calls.append(name)
                await hook({"tool_name": name, "tool_input": arguments}, tool_use_id, None)

    async def receive_response(self) -> Any:
        yield SystemMessage(
            subtype="init",
            data={
                "tools": [*self.options.allowed_tools, *self.extra_tools],
                "mcp_servers": [
                    {"name": name, "status": "connected"} for name in self.options.mcp_servers
                ],
            },
        )
        server = self.options.mcp_servers["wardenbot"]["instance"]
        messages: list[dict[str, Any]] = [{"role": "user", "content": self.prompt}]
        turns = 0
        async with Client(server) as mcp:
            listing = await mcp.list_tools()
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description or "",
                        "parameters": tool.input_schema,
                    },
                }
                for tool in listing.tools
            ]
            while True:
                if turns >= self.options.max_turns:
                    yield _result("error_max_turns", turns, is_error=True)
                    return
                turns += 1
                if self.fail:
                    yield _result("error_during_execution", turns, is_error=True)
                    return
                _, body = chat_completion(
                    {"model": "stub", "messages": messages, "tools": tools}, self.behavior, turns
                )
                reply = body["choices"][0]["message"]
                calls = reply.get("tool_calls") or []
                if not calls:
                    yield AssistantMessage(
                        content=[TextBlock(text=reply["content"])], model="stub-claude"
                    )
                    yield _result("success", turns, result=reply["content"])
                    return
                call = calls[0]
                name = call["function"]["name"]
                arguments = json.loads(call["function"]["arguments"])
                if self.corrupt_arguments and name != "fetch_document":
                    arguments = {"wrong": arguments.get("value")}
                yield AssistantMessage(
                    content=[ToolUseBlock(id=call["id"], name=PREFIX + name, input=arguments)],
                    model="stub-claude",
                )
                await self._hooks(PREFIX + name, arguments, call["id"])
                if name in self.deny:
                    output = "Permission denied."
                else:
                    result = await mcp.call_tool(name, arguments)
                    output = "\n".join(getattr(block, "text", "") for block in result.content)
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})


def _result(subtype: str, turns: int, *, is_error: bool = False, result: str = "") -> Any:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=turns,
        session_id="stub",
        total_cost_usd=0.001,
        usage={"input_tokens": 100, "output_tokens": 20},
        result=result or None,
    )
