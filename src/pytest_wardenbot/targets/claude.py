"""Run a Claude Agent SDK agent against the controlled MCP scenarios.

Install with ``pytest-wardenbot[claude-agent]``. The target serves the harness
tools to Claude Code as an in-process SDK MCP server named ``wardenbot`` (the
model sees ``mcp__wardenbot__fetch_document`` and so on) and keeps your
options for the model, system prompt, hooks and permissions.

For the trial it isolates Claude Code from your machine: no built-in tools
(no Bash, file access or web), none of your MCP servers, no filesystem
settings, skills, plugins or claude.ai connectors, and no saved session. It
checks Claude Code's startup message and stops the trial if any other tool is
available.

A ``PreToolUse`` hook reports every tool call the model asks for, so a call
that your permission callback or hooks deny, or that fails the SDK's argument
validation, still counts as an attempt. ``max_turns`` is passed to the SDK, so
a turn here is one Claude Agent SDK turn (one model response).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Any

try:
    from claude_agent_sdk import (  # type: ignore[import-not-found]
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        HookMatcher,
        ResultMessage,
        SystemMessage,
        TextBlock,
        create_sdk_mcp_server,
        tool,
    )
except ImportError:  # pragma: no cover - exercised by the import guard test
    raise ImportError(
        "The Claude Agent SDK target requires the [claude-agent] extra. "
        "Install with: pip install 'pytest-wardenbot[claude-agent]'"
    ) from None

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents.contracts import TargetRun
from pytest_wardenbot.mcp.harness import MCPHarness
from pytest_wardenbot.mcp.trial_tools import ToolSpec, TrialTools

SERVER = "wardenbot"
PREFIX = f"mcp__{SERVER}__"
_UNBOUNDED = 1_000_000
ClientFactory = Callable[[Any], Any]


def _text(content: list[Any]) -> str:
    return "\n".join(block.text for block in content if isinstance(block, TextBlock))


def _sdk_tool(tools: TrialTools, spec: ToolSpec) -> Any:
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        output = await tools.call(spec.name, arguments)
        return {
            "content": [{"type": "text", "text": output}],
            "is_error": output.startswith("Error:"),
        }

    return tool(spec.name, spec.description, spec.input_schema)(handler)


class ClaudeAgentTarget:
    """An ``AgentTarget`` for an agent built on the Claude Agent SDK.

    ``options`` is your ``ClaudeAgentOptions``. The target keeps its model,
    system prompt, hooks, ``can_use_tool``, permission mode, environment,
    budget and other settings, and replaces only what isolates the trial:
    ``tools``, ``mcp_servers``, ``strict_mcp_config``, ``setting_sources``,
    ``skills``, ``plugins``, ``allowed_tools`` (the harness tools are
    allowed), ``max_turns`` and session persistence.

    ``attach``, ``expose`` and ``task_check`` are passed to ``TrialTools``.
    ``client_factory`` builds the SDK client from the trial's options; it
    exists for tests and defaults to ``ClaudeSDKClient``.
    """

    def __init__(
        self,
        harness: MCPHarness,
        options: Any = None,
        *,
        name: str = "claude-agent",
        attach: bool = True,
        expose: set[str] | frozenset[str] | None = None,
        task_check: Callable[[str], bool] | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        if not isinstance(harness, MCPHarness):
            raise ValueError("ClaudeAgentTarget requires an MCPHarness")
        if options is not None and not isinstance(options, ClaudeAgentOptions):
            raise ValueError("options must be a ClaudeAgentOptions")
        self.harness = harness
        self.options = options or ClaudeAgentOptions()
        self.name = name
        self.attach = attach
        self.expose = expose
        self.task_check = task_check
        self.client_factory = client_factory or (lambda options: ClaudeSDKClient(options=options))
        self.capabilities = TrialTools.CAPABILITIES if attach else TrialTools.TOOL_CAPABILITIES

    async def reset(self, trial_id: str) -> None:
        """Each trial runs in a new Claude Code process with no saved session."""

    def trial_options(self, tools: TrialTools, max_turns: int) -> Any:
        """The isolated options for one trial."""

        async def requested(hook_input: Any, tool_use_id: Any, context: Any) -> Any:
            name = str(hook_input.get("tool_name", ""))
            tools.requested(name.removeprefix(PREFIX), hook_input.get("tool_input"))
            return {}

        hooks = {key: list(value) for key, value in (self.options.hooks or {}).items()}
        hooks["PreToolUse"] = [HookMatcher(hooks=[requested]), *hooks.get("PreToolUse", [])]
        server = create_sdk_mcp_server(SERVER, tools=[_sdk_tool(tools, s) for s in tools.specs])
        extra_args = {**dict(self.options.extra_args or {}), "no-session-persistence": None}
        # A claude.ai login would otherwise load the organization's connectors.
        env = {**dict(self.options.env or {}), "ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
        return dataclasses.replace(
            self.options,
            tools=[],
            mcp_servers={SERVER: server},
            strict_mcp_config=True,
            setting_sources=[],
            skills=[],
            plugins=[],
            allowed_tools=[PREFIX + spec.name for spec in tools.specs],
            max_turns=max_turns,
            hooks=hooks,
            extra_args=extra_args,
            env=env,
            continue_conversation=False,
            resume=None,
        )

    async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
        async with TrialTools(
            self.harness,
            trial_id,
            # Claude Code enforces max_turns itself (one turn per model response).
            max_turns=_UNBOUNDED,
            attach=self.attach,
            expose=self.expose,
            task_check=self.task_check,
        ) as tools:
            allowed = {PREFIX + spec.name for spec in tools.specs}
            options = self.trial_options(tools, max_turns)
            texts: list[str] = []
            result: Any = None
            async with self.client_factory(options) as client:
                await client.query(tools.prompt(task))
                async for message in client.receive_response():
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        _check_isolation(message.data, allowed)
                    elif isinstance(message, AssistantMessage):
                        text = _text(message.content)
                        if text:
                            texts.append(text)
                    elif isinstance(message, ResultMessage):
                        result = message
            if result is None:
                raise WardenBotInfraError("Claude Code ended without a result message")
            exhausted = result.subtype == "error_max_turns"
            if result.is_error and not exhausted:
                raise WardenBotInfraError(f"Claude Code run failed ({result.subtype})")
            final = result.result if isinstance(result.result, str) and result.result else ""
            tools.answer(final or (texts[-1] if texts else ""))
            usage = dict(result.usage or {})
            tools.record_usage(
                {
                    key: value
                    for key, value in usage.items()
                    if key in {"input_tokens", "output_tokens"} and isinstance(value, int | float)
                }
            )
            if isinstance(result.total_cost_usd, int | float):
                tools.record_usage({"cost_usd": result.total_cost_usd})
        turns = int(getattr(result, "num_turns", 0) or 0)
        return dataclasses.replace(tools.result(), turns=turns, limit_exhausted=exhausted)


def _check_isolation(data: Any, allowed: set[str]) -> None:
    """Fail closed if Claude Code offers anything beyond the harness tools."""
    if not isinstance(data, dict):
        raise WardenBotInfraError("Claude Code sent an unreadable startup message")
    extra_tools = sorted(set(data.get("tools") or ()) - allowed)
    servers = {
        str(server.get("name")) if isinstance(server, dict) else str(server)
        for server in data.get("mcp_servers") or ()
    }
    extra_servers = sorted(servers - {SERVER})
    if extra_tools or extra_servers:
        raise WardenBotInfraError(
            "Claude Code offered tools outside the harness, so the trial was stopped: "
            + ", ".join(extra_tools + [f"MCP server {name}" for name in extra_servers])
        )


__all__ = ["ClaudeAgentTarget"]
