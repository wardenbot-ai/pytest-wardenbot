"""The real model API, for ``override``, ``record`` and ``live``.

The key is the original ``OPENAI_API_KEY``, saved by ``install()``; it is held
in memory and sent only to the upstream. The upstream URL is
``WARDENBOT_UPSTREAM_BASE_URL``, else the original ``OPENAI_BASE_URL`` (so a key
meant for another OpenAI-compatible provider is never sent to OpenAI), else
``https://api.openai.com``. ``scripted`` and ``replay`` build no upstream at all.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from pytest_wardenbot.model._errors import ModelEndpointError

UPSTREAM_ENV = "WARDENBOT_UPSTREAM_BASE_URL"
DEFAULT_UPSTREAM = "https://api.openai.com"
# Request headers worth passing on. Never Authorization from the client (it
# carries the dummy key), and nothing here is ever written to a recording.
_FORWARDED_HEADERS = (
    "accept",
    "content-type",
    "openai-beta",
    "openai-organization",
    "openai-project",
)
_TIMEOUT = httpx.Timeout(600.0, connect=30.0)


@dataclass
class UpstreamReply:
    """A reply from the upstream: status, content type, and the body as it arrives."""

    status: int
    content_type: str
    chunks: Iterator[bytes]


class Upstream:
    """Forwards requests to the real model API."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(timeout=_TIMEOUT)

    def __repr__(self) -> str:
        return f"Upstream({self.base_url!r})"  # never the key

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).netloc

    @classmethod
    def from_environment(cls, *, endpoint_url: str | None = None) -> Upstream:
        """The upstream the saved original environment names."""
        from pytest_wardenbot.model._endpoint import ORIGINAL_API_KEY_ENV, ORIGINAL_BASE_URL_ENV

        base = (
            os.environ.get(UPSTREAM_ENV, "").strip()
            or os.environ.get(ORIGINAL_BASE_URL_ENV, "").strip()
            or DEFAULT_UPSTREAM
        )
        if endpoint_url is not None and base.rstrip("/") == endpoint_url.rstrip("/"):
            raise ModelEndpointError(
                f"The upstream URL {base} is the model endpoint itself. Set "
                f"{UPSTREAM_ENV} to the real API."
            )
        key = os.environ.get(ORIGINAL_API_KEY_ENV, "").strip()
        if not key:
            raise ModelEndpointError(
                "This mode calls the real model API, but there is no API key: set "
                "OPENAI_API_KEY before install() runs (the endpoint saves it as "
                f"{ORIGINAL_API_KEY_ENV} and gives the application a dummy key)."
            )
        return cls(base, key)

    def url_for(self, path: str) -> str:
        """Re-base a request path (``/v1/responses``) onto the upstream URL."""
        base_path = urlsplit(self.base_url).path
        if base_path in ("", "/"):
            return self.base_url + path
        return self.base_url + path.removeprefix("/v1")

    def forward(self, path: str, raw: bytes, headers: Mapping[str, str]) -> UpstreamReply:
        """Send the request body unchanged; stream the reply back as it arrives."""
        outgoing = {
            name: value for name, value in headers.items() if name.lower() in _FORWARDED_HEADERS
        }
        outgoing["Authorization"] = f"Bearer {self._api_key}"
        request = self._client.build_request(
            "POST", self.url_for(path), content=raw, headers=outgoing
        )
        try:
            response = self._client.send(request, stream=True)
        except httpx.HTTPError as error:
            raise ModelEndpointError(
                f"Can't reach the upstream {self.host}: {type(error).__name__}"
            ) from None

        def chunks() -> Iterator[bytes]:
            try:
                yield from response.iter_bytes()
            finally:
                response.close()

        return UpstreamReply(
            status=response.status_code,
            content_type=response.headers.get("content-type", "application/json"),
            chunks=chunks(),
        )

    def close(self) -> None:
        self._client.close()


# Turning a recorded stream into a complete body --------------------------------


def sse_data(raw: bytes) -> Iterator[Any]:
    """The JSON payloads of a server-sent event stream, skipping ``[DONE]``."""
    for block in raw.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n\n"):
        data = "".join(
            line[len("data:") :].lstrip() for line in block.split("\n") if line.startswith("data:")
        )
        if data and data != "[DONE]":
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue


def body_from_stream(raw: bytes, api: str) -> dict[str, Any]:
    """The complete body a stream describes: Responses' completed response, or assembled Chat."""
    if api == "responses":
        for event in sse_data(raw):
            if isinstance(event, Mapping) and event.get("type") == "response.completed":
                response = event.get("response")
                if isinstance(response, Mapping):
                    return dict(response)
        raise ModelEndpointError("The upstream stream ended without a response.completed event.")
    content: list[str] = []
    refusal: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    envelope: dict[str, Any] = {}
    finish_reason = "stop"
    usage = None
    for chunk in sse_data(raw):
        if not isinstance(chunk, Mapping):
            continue
        envelope = envelope or {key: chunk.get(key) for key in ("id", "created", "model")}
        usage = chunk.get("usage") or usage
        for choice in chunk.get("choices") or ():
            delta = choice.get("delta") or {}
            content.append(delta.get("content") or "")
            refusal.append(delta.get("refusal") or "")
            for call in delta.get("tool_calls") or ():
                slot = calls.setdefault(
                    call.get("index", 0),
                    {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
                )
                slot["id"] = call.get("id") or slot["id"]
                function = call.get("function") or {}
                slot["function"]["name"] += function.get("name") or ""
                slot["function"]["arguments"] += function.get("arguments") or ""
            finish_reason = choice.get("finish_reason") or finish_reason
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content) or None,
        "refusal": "".join(refusal) or None,
    }
    if calls:
        message["tool_calls"] = [calls[index] for index in sorted(calls)]
    return {
        **envelope,
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": usage,
    }


def assistant_text(body: Mapping[str, Any]) -> str:
    """The assistant's text in a complete Responses or Chat body."""
    if body.get("object") == "response":
        from pytest_wardenbot.model._wire import output_text

        return output_text(body.get("output") or ())
    choices = body.get("choices") or ()
    message = choices[0].get("message") if choices else None
    return str((message or {}).get("content") or "")
