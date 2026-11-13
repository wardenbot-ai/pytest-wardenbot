"""Captured requests and their role-to-text view."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

_TEXT_PART_TYPES = frozenset({"text", "input_text", "output_text"})


def _text_of(content: Any) -> str:
    """Reduce message content to its text: a string, or the text parts of an array, in order."""
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        parts = [
            part["text"]
            for part in content
            if isinstance(part, Mapping)
            and part.get("type") in _TEXT_PART_TYPES
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(parts)
    return ""


def _responses_roles(body: Mapping[str, Any]) -> list[tuple[str, str]]:
    roles: list[tuple[str, str]] = []
    instructions = body.get("instructions")
    if isinstance(instructions, str) and instructions:
        roles.append(("instructions", instructions))
    items = body.get("input")
    if isinstance(items, str):
        roles.append(("user", items))
        return roles
    if not isinstance(items, Sequence):
        return roles
    for item in items:
        if not isinstance(item, Mapping):
            continue
        kind = item.get("type")
        if isinstance(kind, str) and kind.endswith("_output") and "output" in item:
            # function_call_output and the other tool outputs: text the model reads.
            roles.append(("tool", _text_of(item["output"])))
        elif isinstance(item.get("role"), str) and kind in (None, "message"):
            roles.append((item["role"], _text_of(item.get("content"))))
    return roles


def _chat_roles(body: Mapping[str, Any]) -> list[tuple[str, str]]:
    roles: list[tuple[str, str]] = []
    for message in body.get("messages") or ():
        if not isinstance(message, Mapping) or not isinstance(message.get("role"), str):
            continue
        role = "tool" if message["role"] in {"tool", "function"} else message["role"]
        roles.append((role, _text_of(message.get("content"))))
    return roles


def _tool_names(body: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for tool in body.get("tools") or ():
        if not isinstance(tool, Mapping):
            continue
        function = tool.get("function")
        if isinstance(function, Mapping) and isinstance(function.get("name"), str):
            names.append(function["name"])  # Chat Completions
        elif tool.get("type") == "function" and isinstance(tool.get("name"), str):
            names.append(tool["name"])  # Responses function tool
        elif isinstance(tool.get("type"), str):
            names.append(tool["type"])  # Responses hosted tool, such as web_search
    for function in body.get("functions") or ():  # legacy Chat Completions functions
        if isinstance(function, Mapping) and isinstance(function.get("name"), str):
            names.append(function["name"])
    return tuple(names)


@dataclass(frozen=True)
class CapturedRequest:
    """One request the application sent to the model endpoint.

    ``roles`` is the role-to-text view the prompt-side graders read: Responses
    ``instructions`` as ``instructions``, each input item and Chat message as its
    own role, and tool or function-call outputs as ``tool``. Content arrays are
    reduced to their text parts, joined with newlines. Request headers are never
    kept.
    """

    method: str
    path: str
    body: Mapping[str, Any]
    roles: tuple[tuple[str, str], ...] = field(default=())

    @classmethod
    def from_body(cls, method: str, path: str, body: Mapping[str, Any]) -> CapturedRequest:
        """Build the request and its role view from a parsed JSON body."""
        path = path.split("?", 1)[0]
        if path.rstrip("/").endswith("/responses"):
            roles = _responses_roles(body)
        elif path.rstrip("/").endswith("/chat/completions"):
            roles = _chat_roles(body)
        else:
            roles = []
        return cls(method=method, path=path, body=body, roles=tuple(roles))

    @property
    def api(self) -> str:
        """``responses``, ``chat`` or ``other``, from the request path."""
        path = self.path.rstrip("/")
        if path.endswith("/responses"):
            return "responses"
        if path.endswith("/chat/completions"):
            return "chat"
        return "other"

    @property
    def stream(self) -> bool:
        """True when the request asked for server-sent events."""
        return self.body.get("stream") is True

    @property
    def model(self) -> str | None:
        """The model the request named, if any."""
        model = self.body.get("model")
        return model if isinstance(model, str) else None

    @property
    def tools(self) -> tuple[str, ...]:
        """Names of the tools the request offered: function names, or the hosted tool's type."""
        return _tool_names(self.body)

    @property
    def tool_results(self) -> frozenset[str]:
        """Call ids of the tool results the request carries back to the model."""
        ids: set[str] = set()
        items = self.body.get("input")
        for item in items if isinstance(items, Sequence) and not isinstance(items, str) else ():
            kind = item.get("type") if isinstance(item, Mapping) else None
            if isinstance(kind, str) and kind.endswith("_output") and "call_id" in item:
                ids.add(str(item["call_id"]))
        for message in self.body.get("messages") or ():
            if isinstance(message, Mapping) and message.get("role") == "tool":
                ids.add(str(message.get("tool_call_id")))
        return frozenset(ids)

    def text(self, role: str | None = None) -> str:
        """All of the request's text, or one role's, joined with newlines."""
        return "\n".join(text for name, text in self.roles if role is None or name == role)
