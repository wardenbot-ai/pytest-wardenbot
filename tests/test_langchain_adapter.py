"""Tests for the LangChain Runnable adapter (sync + async).

Uses lightweight stub runnables — no real `langchain` install needed, since the
adapter is duck-typed on `.invoke()` / `.ainvoke()`.
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

import pytest

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.base import AsyncChatbotAdapter, ChatbotAdapter
from pytest_wardenbot.adapters.langchain_runnable import (
    AsyncLangChainAdapter,
    LangChainAdapter,
)


class _StubRunnable:
    """Records the last input/config; returns a configurable reply."""

    def __init__(self, reply: Any = "hello from langchain") -> None:
        self.reply = reply
        self.last_input: Any = None
        self.last_config: Any = None

    def invoke(self, value: Any, config: dict[str, Any] | None = None) -> Any:
        self.last_input = value
        self.last_config = config
        return self.reply


class _AsyncStubRunnable:
    def __init__(self, reply: Any = "async hello") -> None:
        self.reply = reply
        self.last_input: Any = None
        self.last_config: Any = None

    async def ainvoke(self, value: Any, config: dict[str, Any] | None = None) -> Any:
        self.last_input = value
        self.last_config = config
        return self.reply


class _BoomRunnable:
    def invoke(self, value: Any, config: dict[str, Any] | None = None) -> Any:
        raise RuntimeError("backend exploded")

    async def ainvoke(self, value: Any, config: dict[str, Any] | None = None) -> Any:
        raise RuntimeError("backend exploded")


# --------------------------------------------------------------------------- #
# Protocol conformance
# --------------------------------------------------------------------------- #


def test_langchain_adapter_satisfies_protocol() -> None:
    assert isinstance(LangChainAdapter(_StubRunnable()), ChatbotAdapter)


def test_async_langchain_adapter_satisfies_protocol() -> None:
    assert isinstance(AsyncLangChainAdapter(_AsyncStubRunnable()), AsyncChatbotAdapter)


def test_rejects_object_without_invoke() -> None:
    with pytest.raises(TypeError, match="invoke"):
        LangChainAdapter(object())


def test_async_rejects_object_without_ainvoke() -> None:
    with pytest.raises(TypeError, match="ainvoke"):
        AsyncLangChainAdapter(_StubRunnable())  # has invoke, not ainvoke


# --------------------------------------------------------------------------- #
# Text extraction across the common LangChain return shapes
# --------------------------------------------------------------------------- #


def test_extracts_plain_string() -> None:
    adapter = LangChainAdapter(_StubRunnable("just a string"))
    assert adapter.send_message("hi").text == "just a string"


def test_extracts_message_content() -> None:
    msg = types.SimpleNamespace(content="from a message object")
    adapter = LangChainAdapter(_StubRunnable(msg))
    assert adapter.send_message("hi").text == "from a message object"


def test_extracts_content_blocks() -> None:
    msg = types.SimpleNamespace(
        content=[{"type": "text", "text": "part one "}, {"type": "text", "text": "part two"}]
    )
    adapter = LangChainAdapter(_StubRunnable(msg))
    assert adapter.send_message("hi").text == "part one part two"


def test_extracts_dict_output_key() -> None:
    adapter = LangChainAdapter(_StubRunnable({"output": "from a chain dict"}))
    assert adapter.send_message("hi").text == "from a chain dict"


def test_rejects_numeric_output() -> None:
    adapter = LangChainAdapter(_StubRunnable(12345))
    with pytest.raises(WardenBotInfraError, match="text_extractor"):
        adapter.send_message("hi")


# --------------------------------------------------------------------------- #
# Input shaping + session config
# --------------------------------------------------------------------------- #


def test_input_key_wraps_prompt_in_dict() -> None:
    stub = _StubRunnable("ok")
    LangChainAdapter(stub, input_key="question").send_message("what time is it?")
    assert stub.last_input == {"question": "what time is it?"}


def test_plain_prompt_passed_through_without_input_key() -> None:
    stub = _StubRunnable("ok")
    LangChainAdapter(stub).send_message("raw prompt")
    assert stub.last_input == "raw prompt"


def test_stateless_call_passes_no_config() -> None:
    stub = _StubRunnable("ok")
    LangChainAdapter(stub).send_message("hi")
    assert stub.last_config is None


def test_session_id_forwarded_via_configurable() -> None:
    stub = _StubRunnable("ok")
    LangChainAdapter(stub).send_message("hi", session_id="sess-42")
    assert stub.last_config == {"configurable": {"session_id": "sess-42"}}


def test_base_config_preserved_and_merged() -> None:
    stub = _StubRunnable("ok")
    LangChainAdapter(stub, config={"tags": ["probe"]}).send_message("hi", session_id="s1")
    assert stub.last_config == {"tags": ["probe"], "configurable": {"session_id": "s1"}}


# --------------------------------------------------------------------------- #
# Errors, redaction, metadata
# --------------------------------------------------------------------------- #


def test_invoke_errors_become_infra_errors() -> None:
    adapter = LangChainAdapter(_BoomRunnable())
    with pytest.raises(WardenBotInfraError, match=r"runnable\.invoke failed"):
        adapter.send_message("hi")


def test_dict_raw_is_redacted_by_default() -> None:
    adapter = LangChainAdapter(_StubRunnable({"output": "hi", "authorization": "Bearer secret"}))
    resp = adapter.send_message("hi")
    assert resp.raw is not None
    assert resp.raw["authorization"] == "[REDACTED]"


def test_keep_sensitive_response_fields_disables_redaction() -> None:
    adapter = LangChainAdapter(
        _StubRunnable({"output": "hi", "authorization": "Bearer secret"}),
        keep_sensitive_response_fields=True,
    )
    resp = adapter.send_message("hi")
    assert resp.raw is not None
    assert resp.raw["authorization"] == "Bearer secret"


def test_reports_latency_and_default_stateful_false() -> None:
    adapter = LangChainAdapter(_StubRunnable("ok"))
    assert adapter.stateful is False
    resp = adapter.send_message("hi")
    assert resp.latency_ms is not None and resp.latency_ms >= 0


def test_stateful_flag_opt_in() -> None:
    assert LangChainAdapter(_StubRunnable(), stateful=True).stateful is True


# --------------------------------------------------------------------------- #
# Async variant
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_async_sends_and_extracts() -> None:
    adapter = AsyncLangChainAdapter(_AsyncStubRunnable("async reply"))
    resp = await adapter.send_message("hi")
    assert resp.text == "async reply"


@pytest.mark.asyncio
async def test_async_forwards_session_id() -> None:
    stub = _AsyncStubRunnable("ok")
    await AsyncLangChainAdapter(stub).send_message("hi", session_id="async-sess")
    assert stub.last_config == {"configurable": {"session_id": "async-sess"}}


@pytest.mark.asyncio
async def test_async_wraps_exceptions() -> None:
    adapter = AsyncLangChainAdapter(_BoomRunnable())
    with pytest.raises(WardenBotInfraError, match=r"runnable\.ainvoke failed"):
        await adapter.send_message("hi")


# --------------------------------------------------------------------------- #
# Extraction edge cases + lifecycle (coverage of the remaining branches)
# --------------------------------------------------------------------------- #


def test_content_blocks_mix_strings_and_dicts() -> None:
    msg = types.SimpleNamespace(content=["plain ", {"type": "text", "text": "block"}])
    assert LangChainAdapter(_StubRunnable(msg)).send_message("hi").text == "plain block"


def test_content_list_without_text_raises() -> None:
    msg = types.SimpleNamespace(content=[{"type": "image", "url": "x"}])
    with pytest.raises(WardenBotInfraError, match="assistant text"):
        LangChainAdapter(_StubRunnable(msg)).send_message("hi")


def test_dict_skips_non_string_value_then_finds_later_key() -> None:
    adapter = LangChainAdapter(_StubRunnable({"output": 123, "text": "the answer"}))
    assert adapter.send_message("hi").text == "the answer"


def test_dict_with_no_known_key_raises() -> None:
    result = {"unexpected": "shape"}
    with pytest.raises(WardenBotInfraError, match="assistant text"):
        LangChainAdapter(_StubRunnable(result)).send_message("hi")


def test_raw_uses_model_dump_when_available() -> None:
    class _Dumpable:
        content = "hi there"

        def model_dump(self) -> dict[str, Any]:
            return {"content": "hi there", "meta": 1}

    resp = LangChainAdapter(_StubRunnable(_Dumpable())).send_message("hi")
    assert resp.text == "hi there"
    assert resp.raw == {"content": "hi there", "meta": 1}


def test_raw_falls_back_when_model_dump_raises() -> None:
    class _BadDump:
        content = "still got text"

        def model_dump(self) -> dict[str, Any]:
            raise ValueError("cannot dump")

    resp = LangChainAdapter(_StubRunnable(_BadDump())).send_message("hi")
    assert resp.text == "still got text"
    assert resp.raw is not None and "repr" in resp.raw


def test_reset_session_and_repr() -> None:
    adapter = LangChainAdapter(_StubRunnable())
    adapter.reset_session("s1")  # no-op, must not raise
    assert repr(adapter) == "LangChainAdapter(runnable=_StubRunnable)"


@pytest.mark.asyncio
async def test_async_reset_session_and_repr() -> None:
    adapter = AsyncLangChainAdapter(_AsyncStubRunnable())
    await adapter.reset_session("s1")  # no-op, must not raise
    assert repr(adapter) == "AsyncLangChainAdapter(runnable=_AsyncStubRunnable)"


@pytest.mark.parametrize("async_adapter", [False, True])
def test_rejects_fixed_session_config(async_adapter: bool) -> None:
    cls = AsyncLangChainAdapter if async_adapter else LangChainAdapter
    stub = _AsyncStubRunnable() if async_adapter else _StubRunnable()
    with pytest.raises(ValueError, match="Remove fixed"):
        cls(stub, config={"configurable": {"thread_id": "shared"}}, session_config_key="thread_id")


def test_thread_mapping_does_not_mutate_base_config() -> None:
    stub = _StubRunnable()
    base = {"tags": ["probe"], "configurable": {"tenant": "demo"}}
    adapter = LangChainAdapter(stub, config=base, session_config_key="thread_id")
    adapter.send_message("hi", session_id="first")
    assert stub.last_config["configurable"] == {"tenant": "demo", "thread_id": "first"}
    adapter.send_message("hi", session_id="second")
    assert stub.last_config["configurable"]["thread_id"] == "second"
    assert base == {"tags": ["probe"], "configurable": {"tenant": "demo"}}


def test_stateful_requires_reset_hook_on_reset() -> None:
    adapter = LangChainAdapter(_StubRunnable(), stateful=True)
    with pytest.raises(WardenBotInfraError, match="require reset_hook"):
        adapter.reset_session("probe")


def test_reset_hook_clears_only_selected_history() -> None:
    history = {"first": ["old"], "second": ["keep"]}

    def reset(sid: str) -> None:
        history.pop(sid, None)

    adapter = LangChainAdapter(_StubRunnable(), stateful=True, reset_hook=reset)
    adapter.reset_session("first")
    assert history == {"second": ["keep"]}


def test_input_mapper_and_custom_extractor() -> None:
    stub = _StubRunnable({"messages": [{"content": "assistant"}]})
    adapter = LangChainAdapter(
        stub,
        input_mapper=lambda prompt: {"messages": [("user", prompt)]},
        text_extractor=lambda result: result["messages"][-1]["content"],
    )
    assert adapter.send_message("hi").text == "assistant"
    assert stub.last_input == {"messages": [("user", "hi")]}


@pytest.mark.parametrize("output", [123, None, {"unexpected": "state"}])
def test_custom_extractor_must_return_string(output: Any) -> None:
    adapter = LangChainAdapter(_StubRunnable(), text_extractor=lambda result: output)
    with pytest.raises(WardenBotInfraError, match="must return a string"):
        adapter.send_message("hi")


def test_custom_extractor_failure_is_infrastructure_error() -> None:
    def extract(result: Any) -> str:
        raise KeyError("messages")

    with pytest.raises(WardenBotInfraError, match="text_extractor failed"):
        LangChainAdapter(_StubRunnable(), text_extractor=extract).send_message("hi")


def test_rejects_nontext_blocks_even_when_they_contain_text_field() -> None:
    msg = types.SimpleNamespace(content=[{"type": "tool_call", "text": "metadata"}])
    with pytest.raises(WardenBotInfraError, match="tool calls"):
        LangChainAdapter(_StubRunnable(msg)).send_message("hi")


def test_sync_reset_failure_is_infrastructure_error() -> None:
    def reset(sid: str) -> None:
        raise RuntimeError("store unavailable")

    adapter = LangChainAdapter(_StubRunnable(), reset_hook=reset, stateful=True)
    with pytest.raises(WardenBotInfraError, match="session was not reset"):
        adapter.reset_session("one")


def test_sync_rejects_async_reset_hook() -> None:
    async def reset(sid: str) -> None:
        pass

    with pytest.raises(WardenBotInfraError, match="reset_hook failed"):
        LangChainAdapter(_StubRunnable(), reset_hook=reset).reset_session("one")


@pytest.mark.asyncio
async def test_async_state_reset_and_thread_mapping() -> None:
    calls = []

    async def reset(sid: str) -> None:
        calls.append(sid)

    stub = _AsyncStubRunnable()
    adapter = AsyncLangChainAdapter(
        stub, stateful=True, reset_hook=reset, session_config_key="thread_id"
    )
    await adapter.send_message("hi", session_id="one")
    assert stub.last_config == {"configurable": {"thread_id": "one"}}
    await adapter.reset_session("one")
    assert calls == ["one"]


@pytest.mark.asyncio
async def test_async_stateful_requires_reset_hook() -> None:
    with pytest.raises(WardenBotInfraError, match="require reset_hook"):
        await AsyncLangChainAdapter(_AsyncStubRunnable(), stateful=True).reset_session("one")


@pytest.mark.asyncio
async def test_async_rejects_unknown_response() -> None:
    with pytest.raises(WardenBotInfraError, match="assistant text"):
        await AsyncLangChainAdapter(_AsyncStubRunnable({"messages": []})).send_message("hi")


@pytest.mark.asyncio
async def test_async_accepts_sync_reset_hook() -> None:
    calls = []
    adapter = AsyncLangChainAdapter(_AsyncStubRunnable(), reset_hook=calls.append)
    await adapter.reset_session("one")
    assert calls == ["one"]


def test_real_langgraph_thread_isolation_and_reset() -> None:
    pytest.importorskip("langgraph")
    from examples.langgraph_state.chatbot import build_adapters, demonstrate_sync

    sync_adapter, _ = build_adapters()
    demonstrate_sync(sync_adapter)


@pytest.mark.asyncio
async def test_real_langgraph_async_thread_isolation_and_reset() -> None:
    pytest.importorskip("langgraph")
    from examples.langgraph_state.chatbot import build_adapters, demonstrate_async

    _, async_adapter = build_adapters()
    await demonstrate_async(async_adapter)


@pytest.mark.parametrize("key", ["", "   "])
def test_session_config_key_must_be_nonempty(key: str) -> None:
    with pytest.raises(ValueError, match="nonempty"):
        LangChainAdapter(_StubRunnable(), session_config_key=key)


def test_rejects_input_key_with_mapper() -> None:
    with pytest.raises(ValueError, match="Choose input_key"):
        LangChainAdapter(_StubRunnable(), input_key="input", input_mapper=lambda prompt: prompt)


def test_rejects_fixed_session_added_after_construction() -> None:
    config: dict[str, Any] = {}
    stub = _StubRunnable()
    adapter = LangChainAdapter(stub, config=config)
    config["configurable"] = {"session_id": "shared"}
    with pytest.raises(ValueError, match="Remove fixed"):
        adapter.send_message("hi", session_id="isolated")
    assert stub.last_input is None


def test_extracts_dict_content_blocks() -> None:
    result = {"content": [{"type": "text", "text": "assistant"}]}
    assert LangChainAdapter(_StubRunnable(result)).send_message("hi").text == "assistant"


def test_input_mapper_failure_is_infrastructure_error() -> None:
    def mapper(prompt: str) -> Any:
        raise ValueError("bad mapping")

    with pytest.raises(WardenBotInfraError, match="input_mapper failed"):
        LangChainAdapter(_StubRunnable(), input_mapper=mapper).send_message("hi")


@pytest.mark.asyncio
async def test_async_reset_failure_is_infrastructure_error() -> None:
    async def reset(sid: str) -> None:
        raise RuntimeError("store unavailable")

    with pytest.raises(WardenBotInfraError, match="session was not reset"):
        await AsyncLangChainAdapter(_AsyncStubRunnable(), reset_hook=reset).reset_session("one")


@pytest.mark.asyncio
async def test_async_custom_extractor_must_return_string() -> None:
    invalid: Any = None
    with pytest.raises(WardenBotInfraError, match="must return a string"):
        await AsyncLangChainAdapter(
            _AsyncStubRunnable(), text_extractor=lambda result: invalid
        ).send_message("hi")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "reply",
    [
        {"role": "user", "content": "user text"},
        {"role": "system", "text": "system text"},
        {"type": "tool", "content": "tool text"},
        {"type": "human", "output": "user text"},
        {"role": "assistant", "content": "intermediate", "tool_calls": [{"name": "tool"}]},
        {"type": "ai", "content": "intermediate", "invalid_tool_calls": [{"name": "tool"}]},
        {"content": "intermediate", "additional_kwargs": {"function_call": {"name": "tool"}}},
        {
            "content": [
                {"type": "text", "text": "intermediate"},
                {"type": "tool_call", "name": "tool"},
            ]
        },
    ],
)
@pytest.mark.asyncio
async def test_default_extraction_rejects_nonassistant_and_pending_tool_dicts(
    asynchronous: bool,
    reply: Any,
) -> None:
    adapter = (
        AsyncLangChainAdapter(_AsyncStubRunnable(reply))
        if asynchronous
        else LangChainAdapter(_StubRunnable(reply))
    )
    with pytest.raises(WardenBotInfraError, match=r"assistant|tool calls"):
        await _send_stateful(adapter, "probe")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("kind", ["human", "system", "tool", "ai-tool", "ai-function"])
@pytest.mark.asyncio
async def test_real_langchain_messages_reject_nonassistant_or_pending_tools(
    asynchronous: bool,
    kind: str,
) -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.messages import (  # type: ignore[import-not-found]
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.runnables import RunnableLambda  # type: ignore[import-not-found]

    replies = {
        "human": HumanMessage(content="user text"),
        "system": SystemMessage(content="system text"),
        "tool": ToolMessage(content="tool result", tool_call_id="call"),
        "ai-tool": AIMessage(
            content="intermediate",
            tool_calls=[
                {"name": "tool", "args": {}, "id": "call"},
            ],
        ),
        "ai-function": AIMessage(
            content="intermediate",
            additional_kwargs={
                "function_call": {"name": "tool", "arguments": "{}"},
            },
        ),
    }
    runnable = RunnableLambda(lambda _: replies[kind])
    adapter = AsyncLangChainAdapter(runnable) if asynchronous else LangChainAdapter(runnable)
    with pytest.raises(WardenBotInfraError, match=r"assistant|tool calls"):
        await _send_stateful(adapter, "probe")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_real_langchain_completed_assistant_message_remains_supported(
    asynchronous: bool,
) -> None:
    pytest.importorskip("langchain_core")
    from langchain_core.messages import AIMessage  # type: ignore[import-not-found]
    from langchain_core.runnables import RunnableLambda  # type: ignore[import-not-found]

    runnable = RunnableLambda(lambda _: AIMessage(content="Completed assistant reply."))
    adapter = AsyncLangChainAdapter(runnable) if asynchronous else LangChainAdapter(runnable)
    assert (await _send_stateful(adapter, "probe")).text == "Completed assistant reply."


class _StatefulRunnable:
    def __init__(self, failure: str | None = None) -> None:
        self.histories: dict[str, list[str]] = {}
        self.ids: list[str] = []
        self.failure = failure

    def invoke(self, prompt: str, *, config: dict[str, Any]) -> Any:
        sid = config["configurable"]["thread_id"]
        self.ids.append(sid)
        history = self.histories.setdefault(sid, [])
        history.append(prompt)
        if self.failure == "invoke":
            raise RuntimeError("backend failed after storing state")
        if self.failure == "extract":
            return {"unrecognized": "state"}
        return str(len(history))

    async def ainvoke(self, prompt: str, *, config: dict[str, Any]) -> Any:
        return self.invoke(prompt, config=config)


async def _send_stateful(adapter: Any, prompt: str, sid: str | None = None) -> Any:
    response = adapter.send_message(prompt, session_id=sid)
    return await response if asyncio.iscoroutine(response) else response


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("saved_id", ["saved", ""])
@pytest.mark.asyncio
async def test_stateful_one_shot_sessions_are_independent_cleaned_and_preserve_explicit_state(
    asynchronous: bool,
    saved_id: str,
) -> None:
    runnable = _StatefulRunnable()
    reset_ids: list[str] = []

    def reset(sid: str) -> None:
        reset_ids.append(sid)
        runnable.histories.pop(sid, None)

    cls = AsyncLangChainAdapter if asynchronous else LangChainAdapter
    adapter = cls(runnable, stateful=True, session_config_key="thread_id", reset_hook=reset)
    assert (await _send_stateful(adapter, "first", saved_id)).text == "1"
    assert (await _send_stateful(adapter, "one shot")).text == "1"
    assert (await _send_stateful(adapter, "another one shot")).text == "1"
    assert reset_ids == runnable.ids[1:]
    assert len(set(reset_ids)) == 2
    assert saved_id not in reset_ids
    assert runnable.histories == {saved_id: ["first"]}
    assert (await _send_stateful(adapter, "second", saved_id)).text == "2"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["invoke", "extract"])
@pytest.mark.asyncio
async def test_stateful_one_shot_cleans_history_after_invocation_or_extraction_failure(
    asynchronous: bool,
    failure: str,
) -> None:
    runnable = _StatefulRunnable(failure)
    reset_ids: list[str] = []

    async def async_reset(sid: str) -> None:
        await asyncio.sleep(0)
        reset_ids.append(sid)
        runnable.histories.pop(sid, None)

    def reset(sid: str) -> None:
        reset_ids.append(sid)
        runnable.histories.pop(sid, None)

    cls = AsyncLangChainAdapter if asynchronous else LangChainAdapter
    adapter = cls(
        runnable,
        stateful=True,
        session_config_key="thread_id",
        reset_hook=async_reset if asynchronous else reset,
    )
    with pytest.raises(WardenBotInfraError):
        await _send_stateful(adapter, "one shot")
    assert reset_ids == runnable.ids
    assert len(reset_ids) == 1
    assert runnable.histories == {}


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_stateful_one_shot_missing_or_failing_cleanup_is_an_infrastructure_error(
    asynchronous: bool,
) -> None:
    runnable = _StatefulRunnable()
    cls = AsyncLangChainAdapter if asynchronous else LangChainAdapter
    adapter = cls(runnable, stateful=True, session_config_key="thread_id")
    with pytest.raises(WardenBotInfraError, match="require reset_hook"):
        await _send_stateful(adapter, "must not invoke")
    assert runnable.ids == []

    def broken_reset(sid: str) -> None:
        raise RuntimeError("checkpoint deletion failed")

    adapter = cls(runnable, stateful=True, session_config_key="thread_id", reset_hook=broken_reset)
    with pytest.raises(WardenBotInfraError, match="session was not reset"):
        await _send_stateful(adapter, "one shot")


@pytest.mark.asyncio
async def test_async_stateful_one_shot_cleans_up_when_invocation_is_cancelled() -> None:
    started = asyncio.Event()

    class CancelledRunnable(_StatefulRunnable):
        async def ainvoke(self, prompt: str, *, config: dict[str, Any]) -> Any:
            self.invoke(prompt, config=config)
            started.set()
            await asyncio.Event().wait()

    runnable = CancelledRunnable()
    reset_ids: list[str] = []

    async def reset(sid: str) -> None:
        await asyncio.sleep(0)
        reset_ids.append(sid)
        runnable.histories.pop(sid, None)

    adapter = AsyncLangChainAdapter(
        runnable,
        stateful=True,
        session_config_key="thread_id",
        reset_hook=reset,
    )
    running = asyncio.create_task(adapter.send_message("one shot"))
    await asyncio.wait_for(started.wait(), 5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert runnable.histories == {}
    assert reset_ids == runnable.ids
    assert len(reset_ids) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_real_graph_one_shot_sessions_are_deleted_and_explicit_state_survives(
    asynchronous: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("langgraph")
    from examples.langgraph_state.chatbot import build_adapters

    sync_adapter, async_adapter = build_adapters()
    adapter: Any = async_adapter if asynchronous else sync_adapter
    graph = adapter._runnable
    ids: list[str] = []
    method = "ainvoke" if asynchronous else "invoke"
    invoke = getattr(graph, method)

    async def ainvoke(payload: Any, *, config: dict[str, Any]) -> Any:
        ids.append(config["configurable"]["thread_id"])
        return await invoke(payload, config=config)

    def sinvoke(payload: Any, *, config: dict[str, Any]) -> Any:
        ids.append(config["configurable"]["thread_id"])
        return invoke(payload, config=config)

    monkeypatch.setattr(graph, method, ainvoke if asynchronous else sinvoke)
    assert (await _send_stateful(adapter, "saved", "saved")).text == "Seen 1 user messages."
    for prompt in ("one shot", "another one shot"):
        assert (await _send_stateful(adapter, prompt)).text == "Seen 1 user messages."
    assert len(set(ids[1:])) == 2
    for sid in ids[1:]:
        config = {"configurable": {"thread_id": sid}}
        snapshot = await graph.aget_state(config) if asynchronous else graph.get_state(config)
        assert snapshot.values == {}
    assert (await _send_stateful(adapter, "saved again", "saved")).text == "Seen 2 user messages."
