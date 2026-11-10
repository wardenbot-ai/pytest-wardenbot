"""Presets for local model servers: Ollama, vLLM and llama.cpp.

All three serve an OpenAI-compatible API, so the presets configure the
existing OpenAI adapters with the server's local address and no provider key.
Nothing here contacts any host other than the server you point it at.

- ``local_chatbot`` (and ``ollama_chatbot``, ``vllm_chatbot``,
  ``llamacpp_chatbot``) returns a chatbot adapter for the chatbot suite.
- ``probe_tool_calling`` asks a model to call a trivial tool once and reports
  whether it produced a structured tool call. ``require_tool_calling`` does the
  same inside an agent target, cached per server and model, and raises
  ``CapabilityUnavailable`` so a model that cannot call tools is reported as
  unsupported instead of resisting by default.
- ``local_base_url`` resolves a server's address.

The chatbot presets need the ``[openai]`` extra; the probes need only the core
install.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from pytest_wardenbot._errors import WardenBotInfraError
from pytest_wardenbot.adapters.base import ChatbotResponse
from pytest_wardenbot.adapters.openai_chat import OpenAIChatAdapter, _import_openai
from pytest_wardenbot.agents.contracts import AgentCapability, CapabilityUnavailable

LocalServerName = Literal["ollama", "vllm", "llamacpp"]


@dataclass(frozen=True)
class LocalServer:
    """A local OpenAI-compatible model server and how to enable tool calls on it."""

    name: str
    label: str
    base_url: str
    tool_calling: str


LOCAL_SERVERS: dict[str, LocalServer] = {
    "ollama": LocalServer(
        name="ollama",
        label="Ollama",
        base_url="http://127.0.0.1:11434/v1",
        tool_calling=(
            "Use a model whose Ollama template supports tools, for example qwen2.5, "
            "llama3.1 or newer, or mistral."
        ),
    ),
    "vllm": LocalServer(
        name="vllm",
        label="vLLM",
        base_url="http://127.0.0.1:8000/v1",
        tool_calling=(
            "Start vLLM with --enable-auto-tool-choice and the --tool-call-parser that "
            "matches the model."
        ),
    ),
    "llamacpp": LocalServer(
        name="llamacpp",
        label="llama.cpp",
        base_url="http://127.0.0.1:8080/v1",
        tool_calling="Start llama-server with --jinja so it applies the model's tool template.",
    ),
}

_PLACEHOLDER_KEY = "local"  # pragma: allowlist secret


def _server(server: str) -> LocalServer:
    try:
        return LOCAL_SERVERS[server]
    except KeyError:
        raise ValueError(
            f"Unknown local server {server!r}. Choose one of: {', '.join(LOCAL_SERVERS)}."
        ) from None


def _ollama_host(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "http://" + value
    parts = urlsplit(value)
    host = parts.hostname or "127.0.0.1"
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    port = parts.port or 11434
    return f"{parts.scheme or 'http'}://{host}:{port}/v1"


def _is_loopback(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "::1"} or host.startswith("127.")


def local_base_url(server: str, base_url: str | None = None) -> str:
    """The OpenAI-compatible base URL for ``server``.

    An explicit ``base_url`` wins. For Ollama, ``OLLAMA_HOST`` is honored the
    way the Ollama CLI reads it. Otherwise the server's default local port.
    """
    preset = _server(server)
    if base_url:
        return base_url.rstrip("/")
    if preset.name == "ollama" and os.environ.get("OLLAMA_HOST", "").strip():
        return _ollama_host(os.environ["OLLAMA_HOST"])
    return preset.base_url


class LocalChatAdapter(OpenAIChatAdapter):
    """``OpenAIChatAdapter`` pointed at a local server, with server-aware errors."""

    name = "local-chat"

    def __init__(self, *, server: str, base_url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._owns_client = True
        self._server = _server(server)
        self._base_url = base_url

    def send_message(self, prompt: str, *, session_id: str | None = None) -> ChatbotResponse:
        try:
            return super().send_message(prompt, session_id=session_id)
        except WardenBotInfraError as exc:
            raise WardenBotInfraError(
                f"{exc} The {self._server.label} server at {self._base_url} did not answer "
                f"for model {self._model!r}. Check that it is running and the model is "
                "available."
            ) from None

    def __repr__(self) -> str:
        return f"LocalChatAdapter(server={self._server.name!r}, model={self._model!r})"


def local_chatbot(
    server: LocalServerName | str,
    model: str,
    *,
    system_prompt: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
    timeout: float = 120.0,
    extra_request_fields: dict[str, Any] | None = None,
) -> LocalChatAdapter:
    """A chatbot adapter for a model served locally by Ollama, vLLM or llama.cpp.

    ``system_prompt`` is sent with every conversation and is available to the
    leak checks for verbatim-overlap detection. ``api_key`` is only needed if
    you started the server with one (vLLM ``--api-key``); it defaults to the
    ``WARDENBOT_LOCAL_API_KEY`` environment variable or a placeholder.
    Requires the ``[openai]`` extra.
    """
    openai = _import_openai()
    url = local_base_url(server, base_url)
    client = openai.OpenAI(
        base_url=url,
        api_key=api_key or os.environ.get("WARDENBOT_LOCAL_API_KEY") or _PLACEHOLDER_KEY,
        max_retries=0,
        timeout=timeout,
        # Don't send local traffic through an HTTP(S)_PROXY from the environment.
        http_client=openai.DefaultHttpxClient(trust_env=not _is_loopback(url)),
    )
    return LocalChatAdapter(
        server=server,
        base_url=url,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        client=client,
        extra_request_fields=extra_request_fields,
    )


def ollama_chatbot(model: str, **kwargs: Any) -> LocalChatAdapter:
    """``local_chatbot("ollama", model, ...)``."""
    return local_chatbot("ollama", model, **kwargs)


def vllm_chatbot(model: str, **kwargs: Any) -> LocalChatAdapter:
    """``local_chatbot("vllm", model, ...)``."""
    return local_chatbot("vllm", model, **kwargs)


def llamacpp_chatbot(model: str, **kwargs: Any) -> LocalChatAdapter:
    """``local_chatbot("llamacpp", model, ...)``."""
    return local_chatbot("llamacpp", model, **kwargs)


# ---------------------------------------------------------------------------
# Tool-calling capability probe
# ---------------------------------------------------------------------------

PROBE_TOOL = "wardenbot_probe"
_PROBE_REQUEST = (
    f"Call the {PROBE_TOOL} tool with the value set to ready. Reply only with the tool call."
)


@dataclass(frozen=True)
class ToolCallingProbe:
    """Whether a model produced a structured tool call when asked to."""

    supported: bool
    detail: str


def _probe_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": _PROBE_REQUEST}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": PROBE_TOOL,
                    "description": "Confirms that tool calling works. Call it when asked.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                },
            }
        ],
    }


def _read_probe(status: int, body: Any, server: LocalServer) -> ToolCallingProbe | None:
    """A verdict for one probe response, or None to try again."""
    if 400 <= status < 500:
        message = ""
        if isinstance(body, dict):
            error = body.get("error")
            message = str(error.get("message", "")) if isinstance(error, dict) else str(error)
        if "tool" in message.lower():
            return ToolCallingProbe(
                False,
                f"{server.label} rejected the tool definitions (HTTP {status}): "
                f"{message[:200] or 'no message'}. {server.tool_calling}",
            )
        raise WardenBotInfraError(
            f"The {server.label} server returned HTTP {status} to the tool-calling probe: "
            f"{message[:200] or 'no message'}"
        )
    if status >= 500:
        raise WardenBotInfraError(
            f"The {server.label} server failed the tool-calling probe with HTTP {status}."
        )
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise WardenBotInfraError(
            f"The {server.label} server returned an unexpected tool-calling probe response."
        ) from None
    for call in message.get("tool_calls") or ():
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and function.get("name") == PROBE_TOOL:
            return ToolCallingProbe(True, "The model returned a structured tool call.")
    return None


async def aprobe_tool_calling(
    server: LocalServerName | str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    attempts: int = 2,
    request_timeout: float = 120.0,
) -> ToolCallingProbe:
    """Ask ``model`` to call a trivial tool and report whether it did.

    One request per attempt, stopping at the first structured call. A model
    that answers in text, or a server that rejects tool definitions, is
    unsupported. A server that can't be reached raises
    ``WardenBotInfraError``: an unreachable server is an error, not a missing
    capability.
    """
    preset = _server(server)
    if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1:
        raise ValueError("attempts must be a positive integer")
    url = local_base_url(server, base_url) + "/chat/completions"
    key = api_key or os.environ.get("WARDENBOT_LOCAL_API_KEY") or _PLACEHOLDER_KEY
    async with httpx.AsyncClient(
        timeout=request_timeout, trust_env=not _is_loopback(url)
    ) as client:
        for _ in range(attempts):
            try:
                response = await client.post(
                    url, json=_probe_payload(model), headers={"Authorization": f"Bearer {key}"}
                )
            except httpx.HTTPError as exc:
                raise WardenBotInfraError(
                    f"Could not reach the {preset.label} server at {url} "
                    f"({type(exc).__name__}). Check that it is running."
                ) from None
            try:
                body = response.json()
            except json.JSONDecodeError:
                body = None
            verdict = _read_probe(response.status_code, body, preset)
            if verdict is not None:
                return verdict
    return ToolCallingProbe(
        False,
        f"The model answered without a structured tool call in {attempts} "
        f"attempt{'s' if attempts > 1 else ''}. {preset.tool_calling}",
    )


def probe_tool_calling(
    server: LocalServerName | str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    attempts: int = 2,
    request_timeout: float = 120.0,
) -> ToolCallingProbe:
    """Synchronous ``aprobe_tool_calling`` for scripts and session fixtures."""
    return asyncio.run(
        aprobe_tool_calling(
            server,
            model,
            base_url=base_url,
            api_key=api_key,
            attempts=attempts,
            request_timeout=request_timeout,
        )
    )


_PROBE_CACHE: dict[tuple[str, str], ToolCallingProbe] = {}


async def require_tool_calling(
    server: LocalServerName | str,
    model: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
) -> ToolCallingProbe:
    """Raise ``CapabilityUnavailable`` unless ``model`` can call tools.

    Call it at the start of an agent target's ``run``. The probe runs once per
    server address and model in the process; later calls reuse the answer.
    """
    key = (local_base_url(server, base_url), model)
    if key not in _PROBE_CACHE:
        _PROBE_CACHE[key] = await aprobe_tool_calling(
            server, model, base_url=base_url, api_key=api_key
        )
    verdict = _PROBE_CACHE[key]
    if not verdict.supported:
        raise CapabilityUnavailable(AgentCapability.TOOL_CALLS, detail=verdict.detail)
    return verdict


def main(argv: list[str] | None = None) -> int:
    """``python -m pytest_wardenbot.local SERVER MODEL [BASE_URL]``: probe tool calling."""
    import sys

    args = sys.argv[1:] if argv is None else argv
    if len(args) not in (2, 3) or args[0] not in LOCAL_SERVERS:
        print(  # noqa: T201
            "usage: python -m pytest_wardenbot.local {ollama,vllm,llamacpp} MODEL [BASE_URL]"
        )
        return 2
    try:
        verdict = probe_tool_calling(args[0], args[1], base_url=args[2] if len(args) == 3 else None)
    except WardenBotInfraError as exc:
        print(f"error: {exc}")  # noqa: T201
        return 2
    status = "supported" if verdict.supported else "unsupported"
    print(f"tool calling: {status}. {verdict.detail}")  # noqa: T201
    return 0 if verdict.supported else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "LOCAL_SERVERS",
    "PROBE_TOOL",
    "LocalChatAdapter",
    "LocalServer",
    "ToolCallingProbe",
    "aprobe_tool_calling",
    "llamacpp_chatbot",
    "local_base_url",
    "local_chatbot",
    "ollama_chatbot",
    "probe_tool_calling",
    "require_tool_calling",
    "vllm_chatbot",
]
