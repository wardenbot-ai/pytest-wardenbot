"""Tests for the LangChain Runnable adapter (sync + async).

Uses lightweight stub runnables — no real `langchain` install needed, since the
adapter is duck-typed on `.invoke()` / `.ainvoke()`.
"""

from __future__ import annotations

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


def test_falls_back_to_str() -> None:
    adapter = LangChainAdapter(_StubRunnable(12345))
    assert adapter.send_message("hi").text == "12345"


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


def test_content_list_without_text_falls_back_to_str() -> None:
    msg = types.SimpleNamespace(content=[{"type": "image", "url": "x"}])
    assert LangChainAdapter(_StubRunnable(msg)).send_message("hi").text == str(msg)


def test_dict_skips_non_string_value_then_finds_later_key() -> None:
    adapter = LangChainAdapter(_StubRunnable({"output": 123, "text": "the answer"}))
    assert adapter.send_message("hi").text == "the answer"


def test_dict_with_no_known_key_falls_back_to_str() -> None:
    result = {"unexpected": "shape"}
    assert LangChainAdapter(_StubRunnable(result)).send_message("hi").text == str(result)


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
