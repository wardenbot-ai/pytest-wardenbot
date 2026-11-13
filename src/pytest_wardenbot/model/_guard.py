"""The egress guard: refuse model API hosts that a client tries to reach directly.

In ``scripted`` and ``replay`` every model request should go to the local
endpoint. A client built with an explicit ``base_url``, or an ``AzureOpenAI``
client, bypasses it and would reach the real API. The guard wraps
``socket.getaddrinfo``, which every HTTP client calls before connecting, and
refuses guarded hostnames; it also wraps ``socket.socket.connect`` and
``connect_ex`` for guarded IP addresses, including the addresses a guarded
hostname resolved to when the lookup didn't name the port. Wrapping (rather
than an audit hook, which can never be removed) lets ``uninstall()`` take it
away. Traffic sent through an HTTP proxy never resolves the target host here,
so the guard can't see it.
"""

from __future__ import annotations

import errno
import ipaddress
import os
import socket
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from pytest_wardenbot.model._errors import ModelEndpointError

DEFAULT_GUARDED = ("api.openai.com",)
_LOOPBACK_NAMES = ("localhost", "127.0.0.1", "::1")


class EgressBlockedError(ModelEndpointError):
    """A client tried to reach a model API host directly instead of the local endpoint.

    The enclosing ``model_endpoint`` block raises it on exit, because SDKs wrap
    connection errors in their own messages. It is deliberately not an
    ``OSError``, so a handler for connection errors around the block can't
    swallow it. The client itself sees a refused connection.
    """


class _RefusedConnection(EgressBlockedError, ConnectionRefusedError):
    """What the socket call raises: a refused connection, for the HTTP client."""


@dataclass(frozen=True)
class GuardedHost:
    """A host the guard refuses, on one port or (``port`` None) on every port."""

    host: str
    port: int | None = None
    is_ip: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "is_ip", _is_ip(self.host))

    def __str__(self) -> str:
        return self.host if self.port is None else f"{self.host}:{self.port}"


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _normalize(host: str) -> str:
    host = host.strip().strip("[]").rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(host.split("%", 1)[0]))
    except ValueError:
        return host


def _is_loopback(host: str) -> bool:
    if host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_guarded(entry: str) -> list[GuardedHost]:
    """Parse ``host``, ``host:port``, ``[v6]:port`` or a URL into the hosts to refuse.

    A path after the host is ignored. A URL guards only its port when it names
    one explicitly. A loopback host (a local model server) from a URL without a
    port guards the scheme's default port, never every local service, and any
    loopback entry is guarded under all its spellings: ``localhost``,
    ``127.0.0.1`` and ``::1``.
    """
    text = entry.strip()
    parts = urlsplit(text if "://" in text else f"//{text}")
    try:
        host, port = parts.hostname, parts.port
    except ValueError as error:
        raise ValueError(f"{entry!r}: {error}") from None
    if not host:
        raise ValueError(f"No host in {entry!r}")
    host = _normalize(host)
    if _is_loopback(host):
        if port is None and "://" in text:
            port = 443 if parts.scheme == "https" else 80
        return [GuardedHost(name, port) for name in _LOOPBACK_NAMES]
    return [GuardedHost(host, port)]


def _port(value: Any) -> int | None:
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if isinstance(value, str) and value and not value.isdigit():
        try:
            return socket.getservbyname(value, "tcp")
        except OSError:
            return None
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
        self.hosts = tuple(dict.fromkeys(hosts))
        self.by_name: dict[str, list[GuardedHost]] = {}
        for host in self.hosts:
            self.by_name.setdefault(host.host, []).append(host)
        self.learned: set[tuple[str, int]] = set()
        self.allowed = (_normalize(allowed[0]), allowed[1])
        self.on_block = on_block
        self.active = True
        self.lock = threading.Lock()
        self.getaddrinfo = socket.getaddrinfo
        self.connect = socket.socket.connect
        self.connect_ex = socket.socket.connect_ex
        self.wrappers: tuple[Any, ...] = ()

    def matching(self, host: str, port: int | None) -> GuardedHost | None:
        for guarded in self.by_name.get(host, ()):
            if guarded.port is None or guarded.port == port:
                return guarded
        return None

    def refuse(self, guarded: Any, action: str) -> _RefusedConnection:
        message = (
            f"The wardenbot egress guard refused to {action} {guarded}: a client bypassed the "
            "local model endpoint and would have reached the real model API. Build the client "
            "without an explicit base_url so it reads OPENAI_BASE_URL, or pass "
            "base_url=install().url (AzureOpenAI: azure_endpoint=install().url)."
        )
        # Record a fresh, never-raised copy: a raised exception pins its frames.
        self.on_block(EgressBlockedError(message))
        return _RefusedConnection(message)

    def check_connect(self, address: Any) -> str | None:
        if not self.active or not isinstance(address, tuple) or len(address) < 2:
            return None
        host = address[0]
        if not isinstance(host, str):
            return None
        host, port = _normalize(host), _port(address[1])
        if (host, port) == self.allowed:
            return None
        with self.lock:
            if port is not None and (host, port) in self.learned:
                return f"{host}:{port}"
        guarded = self.matching(host, port)
        if guarded is not None and guarded.is_ip:
            return str(guarded)
        return None


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
    parsed = [guarded for host in hosts if host.strip() for guarded in parse_guarded(host)]
    with _lock:
        if _active is not None:
            _restore(_active)
        guard = _Guard(parsed, allowed, on_block)

        def getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
            name = host.decode(errors="replace") if isinstance(host, bytes) else host
            if not guard.active or not isinstance(name, str):
                return guard.getaddrinfo(host, port, *args, **kwargs)
            name, number = _normalize(name), _port(port)
            if (name, number) != guard.allowed:
                guarded = guard.matching(name, number)
                if guarded is not None:
                    raise guard.refuse(guarded, "resolve")
                pinned = [h for h in guard.by_name.get(name, ()) if h.port is not None]
                if pinned and number is None:
                    # No port in the lookup: guard the addresses on the pinned ports.
                    results = guard.getaddrinfo(host, port, *args, **kwargs)
                    with guard.lock:
                        for result in results:
                            address = _normalize(str(result[4][0]))
                            guard.learned.update((address, h.port) for h in pinned if h.port)
                    return results
            return guard.getaddrinfo(host, port, *args, **kwargs)

        def connect(self: socket.socket, address: Any) -> Any:
            refused = guard.check_connect(address)
            if refused is not None:
                raise guard.refuse(refused, "connect to")
            return guard.connect(self, address)

        def connect_ex(self: socket.socket, address: Any) -> Any:
            refused = guard.check_connect(address)
            if refused is not None:
                guard.refuse(refused, "connect to")
                return errno.ECONNREFUSED  # connect_ex reports failure, it doesn't raise
            return guard.connect_ex(self, address)

        guard.wrappers = (getaddrinfo, connect, connect_ex)
        socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        _active = guard
    return guard.hosts


def _restore(guard: _Guard) -> None:
    """Deactivate the guard and put back the originals where its wrappers are still in place.

    A wrapper something else saved and later restores (a monkeypatch undone
    after ``uninstall()``) passes every call straight through once inactive.
    """
    guard.active = False
    wrapped_getaddrinfo, wrapped_connect, wrapped_connect_ex = guard.wrappers
    if socket.getaddrinfo is wrapped_getaddrinfo:
        socket.getaddrinfo = guard.getaddrinfo  # type: ignore[assignment]
    if socket.socket.connect is wrapped_connect:
        socket.socket.connect = guard.connect  # type: ignore[method-assign]
    if socket.socket.connect_ex is wrapped_connect_ex:
        socket.socket.connect_ex = guard.connect_ex  # type: ignore[method-assign]


def uninstall_guard() -> None:
    """Remove the guard and restore the original socket functions."""
    global _active
    with _lock:
        if _active is not None:
            _restore(_active)
            _active = None


def guarded_hosts() -> tuple[GuardedHost, ...]:
    """The hosts the active guard refuses, or nothing when no guard is installed."""
    guard = _active
    return guard.hosts if guard is not None else ()


def _reset_after_fork() -> None:
    # The lock may have been held by another thread at the fork.
    global _lock
    _lock = threading.Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)
