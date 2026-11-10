"""Run a LangGraph agent against the controlled MCP scenarios.

Install with ``pytest-wardenbot[langgraph]``. You give the target a function
that builds your graph from a list of LangChain tools; the target supplies the
controlled harness tools, runs one fresh thread per trial, and observes the
graph through LangChain callbacks:

- every model request claims a turn, so ``max_turns`` is enforced before the
  request is sent;
- every tool call the model asks for is reported, so a call your graph blocks
  (a filter node, middleware, an interrupt) still counts as an attempt;
- token usage from the model's messages is recorded.

Before the first trial, the target checks once per process that the graph's
model returns structured tool calls (see ``tool_calling``). A model that
cannot call tools is reported as unsupported instead of resisting by default.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

try:
    from langchain_core.callbacks import AsyncCallbackHandler  # type: ignore[import-not-found]
    from langchain_core.messages import AIMessage, HumanMessage  # type: ignore[import-not-found]
    from langchain_core.tools import BaseTool, StructuredTool  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised by the import guard test
    raise ImportError(
        "The LangGraph target requires the [langgraph] extra. "
        "Install with: pip install 'pytest-wardenbot[langgraph]'"
    ) from None

from pytest_wardenbot.agents.contracts import AgentCapability, CapabilityUnavailable, TargetRun
from pytest_wardenbot.mcp.harness import MCPHarness
from pytest_wardenbot.mcp.trial_tools import ToolSpec, TrialTools, TurnLimitReached

GraphBuilder = Callable[[list[BaseTool]], Any]
PROBE_TOOL = "wardenbot_probe"
_PROBE_REQUEST = (
    f"Call the {PROBE_TOOL} tool with the value set to ready. Reply only with the tool call."
)
_TOOL_CALLING: dict[str, tuple[bool, str]] = {}


def default_input(prompt: str) -> dict[str, Any]:
    """``{"messages": [HumanMessage(prompt)]}``, the input of message-based agents."""
    return {"messages": [HumanMessage(content=prompt)]}


def message_text(message: Any) -> str:
    """The text of a LangChain message, from string or content-block content."""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return "".join(
        block if isinstance(block, str) else str(block.get("text", ""))
        for block in content or ()
        if isinstance(block, str) or (isinstance(block, dict) and block.get("type") == "text")
    )


def default_output(state: Any) -> str:
    """The text of the last AI message in ``state["messages"]``."""
    messages = state.get("messages") if isinstance(state, Mapping) else None
    for message in reversed(messages or ()):
        if isinstance(message, AIMessage):
            return message_text(message)
    return ""


class _ProbeStop(Exception):
    def __init__(self) -> None:
        super().__init__("probe stopped")


class _Observer(AsyncCallbackHandler):
    """Claims turns before model requests and reports requested tool calls."""

    raise_error = True

    def __init__(self, tools: TrialTools) -> None:
        self.tools = tools

    async def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self.tools.turn()

    async def on_llm_start(self, serialized: Any, prompts: Any, **kwargs: Any) -> None:
        self.tools.turn()

    async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        for generations in response.generations:
            for generation in generations:
                message: Any = getattr(generation, "message", None)
                if message is None or not isinstance(message, AIMessage):
                    continue
                for call in message.tool_calls:
                    self.tools.requested(call["name"], call["args"])
                for call in message.invalid_tool_calls:
                    if call.get("name"):
                        self.tools.requested(str(call["name"]), call.get("args"))
                usage = message.usage_metadata
                if usage:
                    self.tools.record_usage(
                        {
                            key: value
                            for key, value in usage.items()
                            if key in {"input_tokens", "output_tokens"}
                            and isinstance(value, int | float)
                        }
                    )


class _ProbeLimit(AsyncCallbackHandler):
    """Stop a probe graph that keeps asking the model after the probe call."""

    raise_error = True

    def __init__(self) -> None:
        self.requests = 0

    async def on_chat_model_start(self, serialized: Any, messages: Any, **kwargs: Any) -> None:
        self.requests += 1
        if self.requests > 3:
            raise _ProbeStop


def _proxy(tools: TrialTools, spec: ToolSpec) -> BaseTool:
    async def call(**arguments: Any) -> str:
        return await tools.call(spec.name, arguments)

    return StructuredTool(
        name=spec.name,
        description=spec.description,
        args_schema=spec.input_schema,
        coroutine=call,
    )


def _rejects_tools(exc: BaseException) -> bool:
    text = str(exc).lower()
    status = getattr(exc, "status_code", None)
    return "tool" in text and (status == 400 or "400" in text or "not support" in text)


async def _built(build_graph: GraphBuilder, tools: list[BaseTool]) -> Any:
    graph = build_graph(tools)
    if inspect.isawaitable(graph):
        graph = await graph
    if not hasattr(graph, "ainvoke"):
        raise TypeError("build_graph must return a compiled graph or another async Runnable")
    return graph


class LangGraphAgentTarget:
    """An ``AgentTarget`` for a LangGraph (or other LangChain Runnable) agent.

    ``build_graph(tools)`` returns your compiled graph, built with the given
    tools in place of your production ones; it may be async. It is called
    once per trial, so each trial starts from a fresh graph and thread.

    - ``tool_calling``: ``None`` (default) checks once per process, per
      target ``name``, that the graph's model returns a structured call to a
      probe tool. ``True`` skips the check (hosted models always support
      tools); ``False`` reports every scenario as unsupported. Give targets for
      different models different names, or the check result is shared.
    - ``attach``, ``expose`` and ``task_check`` are passed to ``TrialTools``.
    - ``input_mapper`` and ``output_mapper`` adapt graphs whose state is not a
      ``messages`` list.
    - ``config`` adds to the run config (tags, metadata, other configurable
      keys). The target sets ``configurable.thread_id`` to the trial ID and
      deletes that thread from the graph's checkpointer when the trial ends.
    """

    def __init__(
        self,
        harness: MCPHarness,
        build_graph: GraphBuilder,
        *,
        name: str = "langgraph",
        tool_calling: bool | None = None,
        attach: bool = True,
        expose: set[str] | frozenset[str] | None = None,
        task_check: Callable[[str], bool] | None = None,
        input_mapper: Callable[[str], Any] = default_input,
        output_mapper: Callable[[Any], str] = default_output,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        if not isinstance(harness, MCPHarness):
            raise ValueError("LangGraphAgentTarget requires an MCPHarness")
        if not callable(build_graph):
            raise ValueError("build_graph must be a callable that takes a list of tools")
        if tool_calling is not None and not isinstance(tool_calling, bool):
            raise ValueError("tool_calling must be None, True or False")
        configurable = dict((config or {}).get("configurable") or {})
        if "thread_id" in configurable:
            raise ValueError("Don't set configurable.thread_id; each trial gets its own thread")
        self.harness = harness
        self.build_graph = build_graph
        self.name = name
        self.tool_calling = tool_calling
        self.attach = attach
        self.expose = expose
        self.task_check = task_check
        self.input_mapper = input_mapper
        self.output_mapper = output_mapper
        self.config = dict(config or {})
        self.capabilities = TrialTools.CAPABILITIES if attach else TrialTools.TOOL_CAPABILITIES
        self._graphs: dict[str, Any] = {}

    async def reset(self, trial_id: str) -> None:
        graph = self._graphs.pop(trial_id, None)
        await _delete_thread(graph, trial_id)

    async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun:
        await self._require_tool_calling()
        async with TrialTools(
            self.harness,
            trial_id,
            max_turns=max_turns,
            attach=self.attach,
            expose=self.expose,
            task_check=self.task_check,
        ) as tools:
            graph = await _built(self.build_graph, [_proxy(tools, spec) for spec in tools.specs])
            self._graphs[trial_id] = graph
            state = await self._invoke(graph, tools.prompt(task), trial_id, _Observer(tools), tools)
            tools.answer(self.output_mapper(state) if state is not None else "")
        return tools.result()

    def _run_config(self, thread_id: str, observer: AsyncCallbackHandler, limit: int) -> Any:
        config = dict(self.config)
        callbacks = list(config.pop("callbacks", None) or ())
        configurable = {**dict(config.pop("configurable", None) or {}), "thread_id": thread_id}
        return {
            **config,
            "configurable": configurable,
            "callbacks": [*callbacks, observer],
            "recursion_limit": limit,
        }

    async def _invoke(
        self,
        graph: Any,
        prompt: str,
        thread_id: str,
        observer: AsyncCallbackHandler,
        tools: TrialTools,
    ) -> Any:
        from langgraph.errors import GraphRecursionError  # type: ignore[import-not-found]

        # Turns are enforced by the observer; the recursion limit only stops a
        # graph that loops without model requests or tool calls.
        limit = 2 * tools.max_turns + 10
        try:
            return await graph.ainvoke(
                self.input_mapper(prompt), self._run_config(thread_id, observer, limit)
            )
        except GraphRecursionError:
            raise TurnLimitReached from None

    async def _require_tool_calling(self) -> None:
        if self.tool_calling is True:
            return
        if self.tool_calling is False:
            raise CapabilityUnavailable(
                AgentCapability.TOOL_CALLS, detail="tool_calling=False was set on the target"
            )
        if self.name not in _TOOL_CALLING:
            _TOOL_CALLING[self.name] = await self._probe()
        supported, detail = _TOOL_CALLING[self.name]
        if not supported:
            raise CapabilityUnavailable(AgentCapability.TOOL_CALLS, detail=detail)

    async def _probe(self) -> tuple[bool, str]:
        """Ask the graph's model to call a probe tool, up to twice."""
        from langgraph.errors import GraphRecursionError  # type: ignore[import-not-found]

        calls = 0

        async def answered(**arguments: Any) -> str:
            nonlocal calls
            calls += 1
            return "Probe received."

        probe = StructuredTool(
            name=PROBE_TOOL,
            description="Confirms that tool calling works. Call it when asked.",
            args_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            coroutine=answered,
        )
        graph = await _built(self.build_graph, [probe])
        for _ in range(2):
            thread_id = f"wardenbot-probe-{uuid.uuid4().hex}"
            try:
                await graph.ainvoke(
                    self.input_mapper(_PROBE_REQUEST),
                    self._run_config(thread_id, _ProbeLimit(), 10),
                )
            except (_ProbeStop, GraphRecursionError):
                pass
            except Exception as exc:
                if _rejects_tools(exc):
                    return False, f"The model rejected tool definitions ({type(exc).__name__})."
                raise
            finally:
                await _delete_thread(graph, thread_id)
            if calls:
                return True, "The graph's model returned a structured tool call."
        return False, "The graph's model answered without a structured tool call in 2 attempts."


async def _delete_thread(graph: Any, thread_id: str) -> None:
    checkpointer = getattr(graph, "checkpointer", None)
    delete: Callable[[str], Awaitable[None]] | None = getattr(checkpointer, "adelete_thread", None)
    if delete is not None:
        await delete(thread_id)


__all__ = ["LangGraphAgentTarget", "default_input", "default_output", "message_text"]
