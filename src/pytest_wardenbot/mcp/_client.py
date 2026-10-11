"""Trusted observation after successful SDK response decoding."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp import Client  # type: ignore[import-not-found]
from mcp_types import (  # type: ignore[import-not-found]
    CallToolResult,
    GetPromptResult,
    Implementation,
    ListToolsResult,
    ReadResourceResult,
    ServerCapabilities,
)

from pytest_wardenbot.agents.contracts import (
    AgentEvent,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    Scenario,
)
from pytest_wardenbot.mcp._server import (
    DOCUMENT_PROMPT,
    DOCUMENT_TOOL,
    DOCUMENT_URI,
    attack_instruction,
)
from pytest_wardenbot.mcp._wire import write_event


class MCPClient:
    """Observed facade backed by a real, context-owned official SDK Client.

    The four methods return unmodified SDK result objects and forward keyword
    arguments. Delivery is recorded only after response decoding succeeds and
    the exact controlled injection appears on the selected primitive. This
    establishes receipt by the integration, never model processing. Context
    ownership remains with ``MCPHarness.trial``; there is no unobserved client
    escape hatch. Metadata properties mirror the underlying SDK client.
    """

    def __init__(self, client: Client, scenario: Scenario, trial_id: str, journal: Path) -> None:
        self._client = client
        self._scenario = scenario
        self._trial_id = trial_id
        self._journal = journal

    @property
    def protocol_version(self) -> str:
        return self._client.protocol_version

    @property
    def server_info(self) -> Implementation | None:
        return self._client.server_info

    @property
    def server_capabilities(self) -> ServerCapabilities:
        return self._client.server_capabilities

    @property
    def instructions(self) -> str | None:
        return self._client.instructions

    def _delivered(self, kind: EventKind, name: str, content: str) -> None:
        if attack_instruction(self._scenario) not in content:
            return
        write_event(
            self._journal,
            AgentEvent(
                trial_id=self._trial_id,
                kind=kind,
                name=name,
                provenance=EventProvenance.HARNESS,
                trust=EventTrust.OBSERVED,
                surface=self._scenario.surface,
                scenario_id=self._scenario.id,
                scenario_version=self._scenario.version,
            ),
        )

    async def list_tools(self, **kwargs: Any) -> ListToolsResult:
        result = await self._client.list_tools(**kwargs)
        if self._scenario.surface is AttackSurface.TOOL_DESCRIPTION:
            for tool in result.tools:
                if tool.name == DOCUMENT_TOOL:
                    self._delivered(EventKind.TOOL_DESCRIPTION, tool.name, tool.description or "")
        return result

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
    ) -> CallToolResult:
        result = await self._client.call_tool(name, arguments, **kwargs)
        if (
            self._scenario.surface is AttackSurface.TOOL_RESULT
            and name == DOCUMENT_TOOL
            and not result.is_error
        ):
            text = "\n".join(getattr(block, "text", "") for block in result.content)
            self._delivered(EventKind.TOOL_RESULT, name, text)
        return result

    async def read_resource(self, uri: str, **kwargs: Any) -> ReadResourceResult:
        result = await self._client.read_resource(uri, **kwargs)
        if self._scenario.surface is AttackSurface.RESOURCE and uri == DOCUMENT_URI:
            text = "\n".join(getattr(block, "text", "") for block in result.contents)
            self._delivered(EventKind.RESOURCE, uri, text)
        return result

    async def get_prompt(
        self, name: str, arguments: dict[str, str] | None = None, **kwargs: Any
    ) -> GetPromptResult:
        result = await self._client.get_prompt(name, arguments, **kwargs)
        if self._scenario.surface is AttackSurface.PROMPT and name == DOCUMENT_PROMPT:
            text = "\n".join(getattr(message.content, "text", "") for message in result.messages)
            self._delivered(EventKind.PROMPT, name, text)
        return result
