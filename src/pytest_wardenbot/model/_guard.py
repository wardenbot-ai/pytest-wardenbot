"""The egress guard: refuse model API hosts that a client tries to reach directly.

In ``scripted`` and ``replay`` every model request should go to the local
endpoint. A client built with an explicit ``base_url``, or an ``AzureOpenAI``
client, bypasses it and would reach the real API. The guard wraps
``socket.getaddrinfo``, which every HTTP client calls before connecting, and
refuses guarded hostnames; it also wraps ``socket.socket.connect`` for guarded
IP literals. An audit hook could only observe, and can't be removed, so the
functions themselves are wrapped. Traffic sent through an HTTP proxy never
resolves the target host here, so the guard can't see it.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from pytest_wardenbot.model._errors import ModelEndpointError

DEFAULT_GUARDED = ("api.openai.com",)


class EgressBlockedError(ModelEndpointError, ConnectionRefusedError):
    """A client tried to reach a model API host directly instead of the local endpoint.

    It is an ``OSError``, so HTTP clients treat it as a failed connection. The
    endpoint also records it, and the enclosing ``model_endpoint`` block raises
    it on exit, because SDKs wrap connection errors in their own messages.
    """


@dataclass(frozen=True)
class GuardedHost:
    """A host the guard refuses, on one port or (``port`` None) on every port."""

    host: str
    port: int | None = None

    @property
    def is_ip(self) -> bool:
        try:
            ipaddress.ip_address(self.host)
        except ValueError:
            return False
        return True

    def matches(self, host: str, port: int | None) -> bool:
        return _normalize(host) == self.host and (self.port is None or self.port == port)

    def __str__(self) -> str:
        return self.host if self.port is None else f"{self.host}:{self.port}"


def _normalize(host: str) -> str:
    host = host.strip().strip("[]").rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        return host


def parse_guarded(entry: str) -> GuardedHost:
    """Parse ``host``, ``host:port``, ``[v6]:port`` or a URL into a guarded host.

    A URL guards only its port when it names one explicitly; ``host`` alone
    guards every port.
    """
    text = entry.strip()
    if "://" in text:
        parts = urlsplit(text)
        if not parts.hostname:
            raise ValueError(f"No host in {entry!r}")
        host = _normalize(parts.hostname)
        port = parts.port
        if port is None and _is_loopback(host):
            # A local model server: guard only its port, never every local service.
            port = 443 if parts.scheme == "https" else 80
        return GuardedHost(host, port)
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        port = rest.removeprefix(":")
        return GuardedHost(_normalize(host), int(port) if port else None)
    if text.count(":") == 1:
        host, port = text.split(":")
        return GuardedHost(_normalize(host), int(port))
    return GuardedHost(_normalize(text), None)


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _Guard:
    def __init__(
        self,
        hosts: Iterable[GuardedHost],
        allowed: tuple[str, int],
        on_block: Callable[[EgressBlockedError], None],
    ) -> None:
        self.hosts = tuple(hosts)
        self.allowed = (_normalize(allowed[0]), allowed[1])
        self.on_block = on_block
        self.getaddrinfo = socket.getaddrinfo
        self.connect = socket.socket.connect
        self.connect_ex = socket.socket.connect_ex

    def refused(self, host: Any, port: Any) -> GuardedHost | None:
        if not isinstance(host, str | bytes):
            return None
        name = host.decode(errors="replace") if isinstance(host, bytes) else host
        number = _port(port)
        if (_normalize(name), number) == self.allowed:
            return None
        return next((guarded for guarded in self.hosts if guarded.matches(name, number)), None)

    def block(self, guarded: GuardedHost, action: str) -> EgressBlockedError:
        error = EgressBlockedError(
            f"The wardenbot egress guard refused to {action} {guarded}: a client bypassed the "
            "local model endpoint and would have reached the real model API. Build the client "
            "without an explicit base_url so it reads OPENAI_BASE_URL, or pass "
            "base_url=install().url (AzureOpenAI: azure_endpoint=install().url)."
        )
        self.on_block(error)
        return error


_lock = threading.Lock()
_active: _Guard | None = None


def install_guard(
    hosts: Iterable[str],
    *,
    allowed: tuple[str, int],
    on_block: Callable[[EgressBlockedError], None],
) -> tuple[GuardedHost, ...]:
    """Wrap the socket functions so ``hosts`` are refused; return the parsed hosts.

    ``allowed`` is the endpoint's own address, never refused. Installing again
    replaces the previous guard.
    """
    global _active
    parsed = tuple(dict.fromkeys(parse_guarded(host) for host in hosts if host.strip()))
    with _lock:
        if _active is not None:
            _restore(_active)
        guard = _Guard(parsed, allowed, on_block)

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            guarded = guard.refused(host, port)
            if guarded is not None:
                raise guard.block(guarded, "resolve")
            return guard.getaddrinfo(host, port, *args, **kwargs)

        def connect(self: socket.socket, address: Any) -> Any:
            if isinstance(address, tuple) and len(address) >= 2:
                guarded = guard.refused(address[0], address[1])
                if guarded is not None and guarded.is_ip:
                    raise guard.block(guarded, "connect to")
            return guard.connect(self, address)

        def connect_ex(self: socket.socket, address: Any) -> Any:
            if isinstance(address, tuple) and len(address) >= 2:
                guarded = guard.refused(address[0], address[1])
                if guarded is not None and guarded.is_ip:
                    raise guard.block(guarded, "connect to")
            return guard.connect_ex(self, address)

        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        _active = guard
    return parsed


def _restore(guard: _Guard) -> None:
    socket.getaddrinfo = guard.getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = guard.connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guard.connect_ex  # type: ignore[method-assign]


def uninstall_guard() -> None:
    """Restore the original socket functions."""
    global _active
    with _lock:
        if _active is not None:
            _restore(_active)
            _active = None


def guarded_hosts() -> tuple[GuardedHost, ...]:
    """The hosts the active guard refuses, or nothing when no guard is installed."""
    guard = _active
    return guard.hosts if guard is not None else ()
