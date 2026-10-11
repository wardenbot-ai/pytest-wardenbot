"""LangChain adapter (sync + async).

Requires the `[langchain]` extra:

    pip install "pytest-wardenbot[langchain]"

Wraps any LangChain **Runnable** — a chat model, an `LLMChain`, an agent
executor, a LangChain Expression Language pipeline, anything with `.invoke()`
(and `.ainvoke()` for the async variant) — as a wardenbot `ChatbotAdapter`.

The adapter is duck-typed and imports no LangChain packages. Supported output
shapes are strings, message content, and common string-valued output keys.
Unknown or non-text outputs raise an infrastructure error; use a validated
``text_extractor`` for graph states or other application-specific responses.

Prompts pass through directly unless ``input_key`` or ``input_mapper`` is set.
Stateful runnables must provide a ``reset_hook`` that clears their backing store.
``session_config_key`` defaults to ``session_id`` for message history; use
``thread_id`` for a checkpointer-backed LangGraph. Fixed session keys in base
config are rejected so independent probes cannot share conversation state.
"""

from __future__ import annotations

import inspect
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse


def _content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type", "text") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
        if parts:
            return "".join(parts)
    return None


def _require_assistant_message(result: Any) -> None:
    """Reject identifiable user/tool messages and unfinished tool requests.

    Generic content-bearing objects without a role retain duck typing. Apps
    returning other message roles or intermediate state need an explicit
    text_extractor that selects their completed assistant reply.
    """
    if isinstance(result, dict):
        fields = result
    else:
        fields = {
            name: getattr(result, name, None)
            for name in (
                "role",
                "type",
                "tool_calls",
                "invalid_tool_calls",
                "function_call",
                "additional_kwargs",
                "content",
            )
        }
    role = fields.get("role")
    if (role is not None and role not in ("assistant", "ai")) or fields.get("type") in (
        "user",
        "human",
        "system",
        "developer",
        "tool",
        "function",
        "remove",
        "HumanMessageChunk",
        "SystemMessageChunk",
        "ToolMessageChunk",
        "FunctionMessageChunk",
    ):
        raise WardenBotInfraError(
            "LangChain response is not an assistant message. "
            "Provide text_extractor= to select your application's completed assistant reply."
        )
    additional = fields.get("additional_kwargs")
    additional = additional if isinstance(additional, dict) else {}
    content = fields.get("content")
    tool_blocks = isinstance(content, list) and any(
        isinstance(block, dict)
        and block.get("type") in ("tool_call", "tool_use", "function_call", "server_tool_call")
        for block in content
    )
    if tool_blocks or any(
        fields.get(key) or additional.get(key)
        for key in ("tool_calls", "invalid_tool_calls", "function_call")
    ):
        raise WardenBotInfraError(
            "LangChain response contains unresolved tool calls. "
            "Invoke the completed application flow or provide text_extractor=."
        )


def _extract_text(result: Any) -> str:
    """Extract recognizable assistant text; never grade an object's repr."""
    if isinstance(result, str):
        return result
    _require_assistant_message(result)
    text = _content_text(getattr(result, "content", None))
    if text is not None:
        return text
    if isinstance(result, dict):
        for key in ("output", "text", "answer", "result", "content"):
            value = result.get(key)
            if isinstance(value, str):
                return value
            if key == "content":
                text = _content_text(value)
                if text is not None:
                    return text
    raise WardenBotInfraError(
        "LangChain response has no recognized assistant text. "
        "Provide text_extractor= that returns the assistant's string response."
    )


def _validated_text(extractor: Callable[[Any], str], result: Any) -> str:
    try:
        text = extractor(result)
    except WardenBotInfraError:
        raise
    except Exception as exc:
        raise WardenBotInfraError(
            "LangChain text_extractor failed to extract assistant text."
        ) from exc
    if not isinstance(text, str):
        raise WardenBotInfraError("LangChain text_extractor must return a string.")
    return text


def _result_to_raw(result: Any) -> dict[str, Any]:
    """Best-effort dict view of an invoke result for `ChatbotResponse.raw`."""
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        try:
            dumped = result.model_dump()
        except Exception:  # best-effort raw view; never fail a probe over it
            dumped = None
        if isinstance(dumped, dict):
            return dumped
    return {"repr": repr(result)}


def _validate_config(config: dict[str, Any] | None, session_config_key: str) -> None:
    if not isinstance(session_config_key, str) or not session_config_key.strip():
        raise ValueError("session_config_key must be a nonempty string.")
    if session_config_key in ((config or {}).get("configurable") or {}):
        raise ValueError(
            f"Remove fixed configurable.{session_config_key} from config; "
            "pass session_id per call so independent probes stay isolated."
        )


def _merge_config(
    base: dict[str, Any] | None, session_id: str | None, session_config_key: str = "session_id"
) -> dict[str, Any] | None:
    _validate_config(base, session_config_key)
    config = dict(base or {})
    if session_id is not None:
        configurable = dict(config.get("configurable") or {})
        configurable[session_config_key] = session_id
        config["configurable"] = configurable
    return config or None


def _require_reset_hook(hook: Any, stateful: bool) -> None:
    if stateful and hook is None:
        raise WardenBotInfraError(
            "Stateful LangChain adapters require reset_hook= to clear backing history "
            "or checkpoints before each probe. Supply history.clear or the checkpointer's "
            "delete_thread/adelete_thread callback, accepting the session ID."
        )


class LangChainAdapter:
    """Synchronous adapter wrapping a LangChain `Runnable`.

    Example:

    ```python
    from langchain_openai import ChatOpenAI
    from pytest_wardenbot.adapters.langchain_runnable import LangChainAdapter

    @pytest.fixture
    def chatbot():
        return LangChainAdapter(ChatOpenAI(model="gpt-4o-mini", temperature=0))
    ```

    Response payloads stored in `ChatbotResponse.raw` are redacted by default;
    pass `keep_sensitive_response_fields=True` to keep the unredacted payload.
    """

    name = "langchain"

    def __init__(
        self,
        runnable: Any,
        *,
        input_key: str | None = None,
        config: dict[str, Any] | None = None,
        text_extractor: Callable[[Any], str] | None = None,
        keep_sensitive_response_fields: bool = False,
        stateful: bool = False,
        session_config_key: str = "session_id",
        input_mapper: Callable[[str], Any] | None = None,
        reset_hook: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        if not hasattr(runnable, "invoke"):
            raise TypeError(
                "LangChainAdapter requires a LangChain Runnable (an object with an "
                f"`.invoke()` method). Got {type(runnable).__name__!r}."
            )
        _validate_config(config, session_config_key)
        if input_key is not None and input_mapper is not None:
            raise ValueError("Choose input_key or input_mapper, not both.")
        if reset_hook is not None and not callable(reset_hook):
            raise TypeError("reset_hook must be callable.")
        self._session_config_key = session_config_key
        self._input_mapper = input_mapper
        self._reset_hook = reset_hook
        self._runnable = runnable
        self._input_key = input_key
        self._config = config
        self._text_extractor = text_extractor or _extract_text
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self.stateful = stateful

    def _build_input(self, prompt: str) -> Any:
        if self._input_mapper is not None:
            try:
                return self._input_mapper(prompt)
            except Exception as exc:
                raise WardenBotInfraError(
                    "LangChain input_mapper failed to map the prompt."
                ) from exc
        return {self._input_key: prompt} if self._input_key else prompt

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        if self.stateful and session_id is None:
            _require_reset_hook(self._reset_hook, self.stateful)
            ephemeral_id = "wardenbot-ephemeral-" + uuid.uuid4().hex
            try:
                return self._send_message(prompt, session_id=ephemeral_id)
            finally:
                self.reset_session(ephemeral_id)
        return self._send_message(prompt, session_id=session_id)

    def _send_message(self, prompt: str, *, session_id: str | None) -> ChatbotResponse:
        payload = self._build_input(prompt)
        config = _merge_config(self._config, session_id, self._session_config_key)

        start = time.perf_counter()
        try:
            result = (
                self._runnable.invoke(payload, config=config)
                if config is not None
                else self._runnable.invoke(payload)
            )
        except Exception as exc:
            raise WardenBotInfraError(
                f"LangChain runnable.invoke failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _validated_text(self._text_extractor, result)
        raw = _result_to_raw(result)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        _require_reset_hook(self._reset_hook, self.stateful)
        if self._reset_hook is None:
            return
        try:
            result = self._reset_hook(session_id)
            if inspect.isawaitable(result):
                if inspect.iscoroutine(result):
                    result.close()
                raise TypeError("Use a synchronous reset_hook with LangChainAdapter.")
            if result is not None:
                raise TypeError("reset_hook must return None.")
        except Exception as exc:
            raise WardenBotInfraError(
                "LangChain reset_hook failed; session was not reset."
            ) from exc

    def __repr__(self) -> str:
        return f"LangChainAdapter(runnable={type(self._runnable).__name__})"


class AsyncLangChainAdapter:
    """Async counterpart to `LangChainAdapter`, using `.ainvoke()`.

    Same duck-typed extraction and error wrapping. Useful for parallel fan-out
    in user-written async suites; the shipped v0.1 tests are sync, so pass
    through `to_sync(...)` to consume it from the default `chatbot` fixture.
    """

    name = "async-langchain"

    def __init__(
        self,
        runnable: Any,
        *,
        input_key: str | None = None,
        config: dict[str, Any] | None = None,
        text_extractor: Callable[[Any], str] | None = None,
        keep_sensitive_response_fields: bool = False,
        stateful: bool = False,
        session_config_key: str = "session_id",
        input_mapper: Callable[[str], Any] | None = None,
        reset_hook: Callable[[str], Awaitable[None] | None] | None = None,
    ) -> None:
        if not hasattr(runnable, "ainvoke"):
            raise TypeError(
                "AsyncLangChainAdapter requires a LangChain Runnable with an "
                f"`.ainvoke()` method. Got {type(runnable).__name__!r}."
            )
        _validate_config(config, session_config_key)
        if input_key is not None and input_mapper is not None:
            raise ValueError("Choose input_key or input_mapper, not both.")
        if reset_hook is not None and not callable(reset_hook):
            raise TypeError("reset_hook must be callable.")
        self._session_config_key = session_config_key
        self._input_mapper = input_mapper
        self._reset_hook = reset_hook
        self._runnable = runnable
        self._input_key = input_key
        self._config = config
        self._text_extractor = text_extractor or _extract_text
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self.stateful = stateful

    def _build_input(self, prompt: str) -> Any:
        if self._input_mapper is not None:
            try:
                return self._input_mapper(prompt)
            except Exception as exc:
                raise WardenBotInfraError(
                    "LangChain input_mapper failed to map the prompt."
                ) from exc
        return {self._input_key: prompt} if self._input_key else prompt

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        if self.stateful and session_id is None:
            _require_reset_hook(self._reset_hook, self.stateful)
            ephemeral_id = "wardenbot-ephemeral-" + uuid.uuid4().hex
            try:
                return await self._send_message(prompt, session_id=ephemeral_id)
            finally:
                await self.reset_session(ephemeral_id)
        return await self._send_message(prompt, session_id=session_id)

    async def _send_message(self, prompt: str, *, session_id: str | None) -> ChatbotResponse:
        payload = self._build_input(prompt)
        config = _merge_config(self._config, session_id, self._session_config_key)

        start = time.perf_counter()
        try:
            result = (
                await self._runnable.ainvoke(payload, config=config)
                if config is not None
                else await self._runnable.ainvoke(payload)
            )
        except Exception as exc:
            raise WardenBotInfraError(
                f"LangChain runnable.ainvoke failed: {type(exc).__name__}: {exc}"
            ) from exc
        elapsed_ms = (time.perf_counter() - start) * 1000

        text = _validated_text(self._text_extractor, result)
        raw = _result_to_raw(result)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        _require_reset_hook(self._reset_hook, self.stateful)
        if self._reset_hook is None:
            return
        try:
            result = self._reset_hook(session_id)
            if inspect.isawaitable(result):
                result = await result
            if result is not None:
                raise TypeError("reset_hook must return None.")
        except Exception as exc:
            raise WardenBotInfraError(
                "LangChain reset_hook failed; session was not reset."
            ) from exc

    def __repr__(self) -> str:
        return f"AsyncLangChainAdapter(runnable={type(self._runnable).__name__})"
