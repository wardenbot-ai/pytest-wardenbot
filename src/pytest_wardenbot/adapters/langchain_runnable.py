"""LangChain adapter (sync + async).

Requires the `[langchain]` extra:

    pip install "pytest-wardenbot[langchain]"

Wraps any LangChain **Runnable** — a chat model, an `LLMChain`, an agent
executor, a LangChain Expression Language pipeline, anything with `.invoke()`
(and `.ainvoke()` for the async variant) — as a wardenbot `ChatbotAdapter`.

The adapter is deliberately *duck-typed*: it never imports `langchain`. It
calls the runnable's `.invoke(prompt)` and extracts text from whatever comes
back (a plain string, a message object with `.content`, or a dict with a common
output key). That keeps it resilient across LangChain's frequent releases —
there is no version-pinned surface here, only the stable `Runnable` contract.

**Input shape.** By default the prompt string is passed straight to
`.invoke(prompt)`, which is what chat models and most LCEL chains expect. If
your runnable wants a dict (e.g. a prompt template keyed on ``question``), pass
``input_key="question"`` and the adapter calls ``.invoke({"question": prompt})``.

**Sessions / multi-turn.** A bare runnable is stateless, so this adapter is
`stateful=False` by default and the multi-turn jailbreak test will warn. To run
multi-turn meaningfully, wrap your runnable with LangChain's
``RunnableWithMessageHistory`` (which reads ``configurable.session_id``) and
construct the adapter with ``stateful=True``; the adapter forwards each
``session_id`` into the run config under ``configurable.session_id``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot._redaction import redact_response_payload
from pytest_wardenbot.adapters.base import ChatbotResponse


def _extract_text(result: Any) -> str:
    """Pull assistant text from a LangChain `invoke()` result.

    Handles the common return shapes:
    - a plain ``str`` (string-output chains, ``StrOutputParser``);
    - a message object with a ``.content`` attribute (``AIMessage`` /
      ``BaseMessage``), where ``content`` is a string or a list of content
      blocks (``[{"type": "text", "text": ...}]``);
    - a ``dict`` with a common output key (``output``, ``text``, ``answer``,
      ``result``, ``content``).

    Falls back to ``str(result)`` so a probe always gets *something* to grade.
    """
    if isinstance(result, str):
        return result

    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        if parts:
            return "".join(parts)

    if isinstance(result, dict):
        for key in ("output", "text", "answer", "result", "content"):
            value = result.get(key)
            if isinstance(value, str):
                return value

    return str(result)


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


def _merge_config(base: dict[str, Any] | None, session_id: str | None) -> dict[str, Any] | None:
    """Merge the base run config with the per-call session id (if any).

    Session id is placed under ``configurable.session_id`` — the key
    ``RunnableWithMessageHistory`` reads — without clobbering an existing one.
    """
    config = dict(base or {})
    if session_id is not None:
        configurable = dict(config.get("configurable") or {})
        configurable.setdefault("session_id", session_id)
        config["configurable"] = configurable
    return config or None


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
    ) -> None:
        if not hasattr(runnable, "invoke"):
            raise TypeError(
                "LangChainAdapter requires a LangChain Runnable (an object with an "
                f"`.invoke()` method). Got {type(runnable).__name__!r}."
            )
        self._runnable = runnable
        self._input_key = input_key
        self._config = config
        self._text_extractor = text_extractor or _extract_text
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self.stateful = stateful

    def _build_input(self, prompt: str) -> Any:
        return {self._input_key: prompt} if self._input_key else prompt

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        payload = self._build_input(prompt)
        config = _merge_config(self._config, session_id)

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

        text = self._text_extractor(result)
        raw = _result_to_raw(result)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    def reset_session(self, session_id: str) -> None:
        # History (if any) lives in the user's RunnableWithMessageHistory store,
        # not in this wrapper, so there is nothing to reset here.
        del session_id

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
    ) -> None:
        if not hasattr(runnable, "ainvoke"):
            raise TypeError(
                "AsyncLangChainAdapter requires a LangChain Runnable with an "
                f"`.ainvoke()` method. Got {type(runnable).__name__!r}."
            )
        self._runnable = runnable
        self._input_key = input_key
        self._config = config
        self._text_extractor = text_extractor or _extract_text
        self._keep_sensitive_response_fields = keep_sensitive_response_fields
        self.stateful = stateful

    def _build_input(self, prompt: str) -> Any:
        return {self._input_key: prompt} if self._input_key else prompt

    async def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        payload = self._build_input(prompt)
        config = _merge_config(self._config, session_id)

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

        text = self._text_extractor(result)
        raw = _result_to_raw(result)
        stored_raw = raw if self._keep_sensitive_response_fields else redact_response_payload(raw)
        return ChatbotResponse(text=text, raw=stored_raw, latency_ms=elapsed_ms)

    async def reset_session(self, session_id: str) -> None:
        del session_id

    def __repr__(self) -> str:
        return f"AsyncLangChainAdapter(runnable={type(self._runnable).__name__})"
