"""Owned local MCP transports with per-trial authoritative recording."""

from __future__ import annotations

import asyncio
import json
import math
import os
import socket
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, TextIO

from mcp import Client, StdioServerParameters  # type: ignore[import-not-found]
from mcp.client.stdio import stdio_client  # type: ignore[import-not-found]
from mcp.server import MCPServer  # type: ignore[import-not-found]

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.agents.contracts import HarnessTrace, Scenario
from pytest_wardenbot.mcp._client import MCPClient
from pytest_wardenbot.mcp._server import DOCUMENT, build_server
from pytest_wardenbot.mcp._wire import event_from_dict, scenario_to_dict

Transport = Literal["memory", "stdio", "http"]
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-11-25", "2026-07-28"})
_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])


@dataclass
class TrialResources:
    """Non-sensitive transport diagnostics retained after teardown."""

    process_id: int | None = None
    port: int | None = None
    protocol_version: str | None = None
    closed: bool = False


@contextmanager
def _stdio_errlog() -> Iterator[TextIO]:
    # The SDK requires an OS file descriptor for subprocess stderr.
    with open(os.devnull, "w", encoding="utf-8") as stream:
        yield stream


def _resources_closed(resources: TrialResources) -> bool:
    if resources.process_id is not None:
        try:
            os.kill(resources.process_id, 0)
        except ProcessLookupError:
            pass
        else:
            return False
    if resources.port is not None:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", resources.port)) == 0:
                return False
    return True


class MCPHarness:
    """Serve one scenario through fresh, owned local transports for each trial.

    Targets use ``async with harness.trial(trial_id) as client``. The context
    owns the SDK client, server, subprocess/socket, and private recording files.
    ``observe`` is suitable for the core runner's independent evidence hook.
    Harnesses never connect to arbitrary addresses or execute remote effects.
    ``startup_timeout`` bounds service startup and client negotiation separately.
    ``shutdown_timeout`` bounds the HTTP service shutdown; the official SDK
    supplies its own bounded stdio process-tree shutdown and escalation.
    """

    def __init__(
        self,
        scenario: Scenario,
        *,
        transport: Transport = "memory",
        protocol_version: str = "2026-07-28",
        startup_timeout: float = 5,
        shutdown_timeout: float = 5,
        attack_enabled: bool = True,
        document_text: str = DOCUMENT,
        injection_text: str | None = None,
    ) -> None:
        if transport not in {"memory", "stdio", "http"}:
            raise ValueError("Unsupported local MCP transport")
        if protocol_version not in SUPPORTED_PROTOCOL_VERSIONS:
            raise ValueError("Unsupported MCP protocol version; supported: 2025-11-25, 2026-07-28")
        if not isinstance(attack_enabled, bool):
            raise ValueError("attack_enabled must be a boolean")
        if not isinstance(document_text, str) or not document_text.strip():
            raise ValueError("A benign document must contain text")
        if injection_text is not None and (
            not isinstance(injection_text, str) or not injection_text.strip()
        ):
            raise ValueError("An injection override must contain text")
        if any(
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
            or value <= 0
            for value in (startup_timeout, shutdown_timeout)
        ):
            raise ValueError("MCP transport deadlines must be positive")
        self.scenario = scenario
        self.transport = transport
        self.protocol_version = protocol_version
        self.startup_timeout = startup_timeout
        self.shutdown_timeout = shutdown_timeout
        self.attack_enabled = attack_enabled
        self.document_text = document_text
        self.injection_text = injection_text
        self.resources: dict[str, TrialResources] = {}
        self._traces: dict[str, HarnessTrace] = {}

    def observe(self, trial_id: str) -> HarnessTrace:
        return self._traces.get(trial_id, HarnessTrace(trial_id=trial_id))

    @asynccontextmanager
    async def _endpoint(
        self, directory: Path, resources: TrialResources, trial_id: str
    ) -> AsyncIterator[MCPServer | AbstractAsyncContextManager[tuple[Any, Any]] | str]:
        if self.transport == "stdio":
            (directory / "config.json").write_text(
                json.dumps(
                    {
                        "scenario": scenario_to_dict(self.scenario),
                        "trial_id": trial_id,
                        "attack_enabled": self.attack_enabled,
                        "document_text": self.document_text,
                        "injection_text": self.injection_text,
                    }
                ),
                encoding="utf-8",
            )
            # The SDK passes a minimal default environment, not provider keys.
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "pytest_wardenbot.mcp._stdio", str(directory)],
                env={"PYTHONPATH": _PACKAGE_ROOT},
            )
            # Private subprocess diagnostics must not leak configuration data.
            with _stdio_errlog() as errlog:
                yield stdio_client(parameters, errlog=errlog)
            return
        server = build_server(
            self.scenario,
            trial_id,
            directory / "events.jsonl",
            attack_enabled=self.attack_enabled,
            document_text=self.document_text,
            injection_text=self.injection_text,
        )
        if self.transport == "memory":
            yield server
            return
        import uvicorn  # type: ignore[import-not-found]

        class LocalHTTPServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self) -> Iterator[None]:
                # The embedding application's signal handlers own the process.
                yield

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        resources.port = sock.getsockname()[1]
        host = LocalHTTPServer(
            uvicorn.Config(
                server.streamable_http_app(json_response=True), log_level="critical", lifespan="on"
            )
        )
        task = asyncio.create_task(host.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(self.startup_timeout):
                while not host.started:
                    if task.done():
                        await task
                        raise WardenBotInfraError("Local MCP HTTP server failed to start")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{resources.port}/mcp"
        finally:
            host.should_exit = True
            try:
                async with asyncio.timeout(self.shutdown_timeout):
                    await asyncio.shield(task)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                sock.close()

    @asynccontextmanager
    async def trial(self, trial_id: str) -> AsyncIterator[MCPClient]:
        """Yield an observed SDK client facade, then close all trial resources."""
        if trial_id in self.resources:
            raise WardenBotInfraError("MCP trial identifiers cannot be reused")
        resources = self.resources[trial_id] = TrialResources()
        completed = False
        with TemporaryDirectory(prefix="pw-mcp-") as temporary:
            directory = Path(temporary)
            try:
                async with self._endpoint(directory, resources, trial_id) as endpoint:
                    mode = "legacy" if self.protocol_version == "2025-11-25" else "auto"
                    async with AsyncExitStack() as stack:
                        async with asyncio.timeout(self.startup_timeout):
                            client = await stack.enter_async_context(
                                Client(
                                    endpoint, mode=mode, read_timeout_seconds=self.startup_timeout
                                )
                            )
                        resources.protocol_version = client.protocol_version
                        if resources.protocol_version != self.protocol_version:
                            raise WardenBotInfraError("MCP protocol negotiation failed")
                        yield MCPClient(
                            client,
                            self.scenario,
                            trial_id,
                            directory / "events.jsonl",
                            attack_enabled=self.attack_enabled,
                            injection_text=self.injection_text,
                        )
                completed = True
            except asyncio.CancelledError:
                raise
            except Exception:
                if resources.protocol_version is not None and (
                    resources.protocol_version != self.protocol_version
                ):
                    raise WardenBotInfraError(
                        "Local MCP harness negotiated an unsupported protocol version"
                    ) from None
                raise WardenBotInfraError(
                    "Local MCP harness transport or target execution failed"
                ) from None
            finally:
                journal = directory / "events.jsonl"
                events = (
                    tuple(
                        event_from_dict(json.loads(line))
                        for line in journal.read_text(encoding="utf-8").splitlines()
                    )
                    if journal.exists()
                    else ()
                )
                pid_file = directory / "pid"
                if pid_file.exists():
                    resources.process_id = int(pid_file.read_text(encoding="ascii"))
                resources.closed = _resources_closed(resources)
                self._traces[trial_id] = HarnessTrace(
                    trial_id=trial_id, events=events, complete=completed and resources.closed
                )
                if not resources.closed:
                    raise WardenBotInfraError(
                        "Local MCP harness resources failed to close"
                    ) from None
