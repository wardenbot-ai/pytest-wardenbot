"""The egress guard refuses model API hosts that a client tries to reach directly.

Before installing the endpoint, each test replaces the real resolver with one
that fails, so a broken guard fails the test instead of reaching the network.
"""

from __future__ import annotations

import contextlib
import errno
import os
import socket
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from pytest_wardenbot.model import (
    EgressBlockedError,
    Endpoint,
    ModelEndpointError,
    install,
    model_endpoint,
    uninstall,
)
from pytest_wardenbot.model._guard import guarded_hosts, parse_guarded
from tests.model_support import allow_upstream, clean_environment

REAL_GETADDRINFO = socket.getaddrinfo
REAL_CONNECT = socket.socket.connect


REAL_CONNECT_EX = socket.socket.connect_ex
LOCAL = {"127.0.0.1", "localhost", "::1"}


def _no_real_network(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
    if host in LOCAL:
        return REAL_GETADDRINFO(host, port, *args, **kwargs)
    raise AssertionError(f"reached the real resolver for {host!r}")


def _no_real_connect(self: socket.socket, address: Any) -> Any:
    if isinstance(address, tuple) and address[0] not in LOCAL:
        raise AssertionError(f"reached a real connect to {address!r}")
    return REAL_CONNECT(self, address)


def _no_real_connect_ex(self: socket.socket, address: Any) -> Any:
    if isinstance(address, tuple) and address[0] not in LOCAL:
        raise AssertionError(f"reached a real connect_ex to {address!r}")
    return REAL_CONNECT_EX(self, address)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_environment(monkeypatch)
    uninstall()
    monkeypatch.setattr(socket, "getaddrinfo", _no_real_network)
    monkeypatch.setattr(socket.socket, "connect", _no_real_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _no_real_connect_ex)


@pytest.fixture
def guarded(no_network: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[Endpoint]:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm-gateway.example.invalid/v1")
    endpoint = install(mode="scripted")
    try:
        yield endpoint
    finally:
        uninstall()


def test_guarded_hosts_include_the_defaults_and_the_original_base_url(guarded: Endpoint) -> None:
    hosts = {str(host) for host in guarded_hosts()}
    assert hosts == {"api.openai.com", "llm-gateway.example.invalid"}


def test_explicit_base_url_to_openai_is_refused(guarded: Endpoint) -> None:
    with (
        pytest.raises(EgressBlockedError, match=r"refused to resolve api\.openai\.com") as error,
        model_endpoint("bypass", script="x"),
        pytest.raises(httpx.ConnectError, match=r"api\.openai\.com"),
    ):
        httpx.get("https://api.openai.com/v1/models", timeout=5)
    assert "base_url=install().url" in str(error.value)


def test_the_original_base_url_host_is_refused(guarded: Endpoint) -> None:
    with (
        pytest.raises(EgressBlockedError, match=r"llm-gateway\.example\.invalid"),
        model_endpoint("bypass", script="x"),
        contextlib.suppress(httpx.ConnectError),  # the application swallows the failure
    ):
        httpx.post("https://LLM-Gateway.example.invalid./v1/responses", json={})


def test_the_endpoint_itself_still_works(guarded: Endpoint) -> None:
    assert guarded.url is not None
    with model_endpoint("ok", script="fine"):
        reply = httpx.post(guarded.url + "/responses", json={"input": "x"}, timeout=10)
    assert reply.json()["output_text"] == "fine"


def test_bypass_outside_a_block_is_recorded_on_the_endpoint(guarded: Endpoint) -> None:
    with pytest.raises(OSError, match=r"api\.openai\.com"):
        socket.getaddrinfo("api.openai.com", 443)
    assert isinstance(guarded.errors[-1], EgressBlockedError)


def test_ip_literals_are_refused_in_connect(
    no_network: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WARDENBOT_CONFIG", str(tmp_path / "wardenbot.toml"))
    (tmp_path / "wardenbot.toml").write_text(
        '[model]\nguard_hosts = ["203.0.113.7:9", "[2001:db8::1]:443", "llm.internal"]\n',
        encoding="utf-8",
    )
    endpoint = install(mode="replay")
    try:
        hosts = {str(host) for host in guarded_hosts()}
        assert {"203.0.113.7:9", "2001:db8::1:443", "llm.internal"} <= hosts
        with socket.socket() as sock, pytest.raises(EgressBlockedError, match="connect to"):
            sock.connect(("203.0.113.7", 9))
        with socket.socket() as sock:
            assert sock.connect_ex(("203.0.113.7", 9)) == errno.ECONNREFUSED
        with pytest.raises(EgressBlockedError, match=r"resolve llm\.internal"):
            socket.getaddrinfo("llm.internal", 8080)
        assert len(endpoint.errors) == 3
    finally:
        uninstall()


def test_a_loopback_original_base_url_guards_only_its_port(
    no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    endpoint = install(mode="scripted")
    try:
        assert "localhost:11434" in {str(host) for host in guarded_hosts()}
        with pytest.raises(EgressBlockedError, match="localhost:11434"):
            socket.getaddrinfo("localhost", 11434)
        assert socket.getaddrinfo("localhost", 5432)  # another local service is fine
        assert endpoint.url is not None
        with model_endpoint("ok", script="fine"):
            assert httpx.post(endpoint.url + "/responses", json={}, timeout=10).status_code == 200
    finally:
        uninstall()


def test_the_block_error_is_not_an_os_error(guarded: Endpoint) -> None:
    with (
        pytest.raises(EgressBlockedError) as error,
        model_endpoint("bypass", script="x"),
        contextlib.suppress(OSError),  # an app's connection-error handler
    ):
        socket.getaddrinfo("api.openai.com", 443)
    assert not isinstance(error.value, OSError)  # so suppress(ConnectionError) can't hide it
    assert error.value.__traceback__ is not None


def test_a_hostname_pinned_to_a_port_is_guarded_whatever_the_lookup(
    no_network: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "wardenbot.toml").write_text('[model]\nguard_hosts = ["localhost:8443"]\n')
    monkeypatch.setenv("WARDENBOT_CONFIG", str(tmp_path / "wardenbot.toml"))
    install(mode="replay")
    try:
        with pytest.raises(OSError, match="localhost:8443"):
            socket.getaddrinfo("localhost", "8443")
        resolved = socket.getaddrinfo("localhost", None)  # no port: the addresses are learned
        address = resolved[0][4][0]
        with socket.socket(resolved[0][0]) as sock, pytest.raises(OSError, match=":8443"):
            sock.connect((address, 8443))
        assert socket.getaddrinfo("localhost", 5432)  # other ports stay open
    finally:
        uninstall()


def test_loopback_hosts_are_guarded_under_every_spelling(
    no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    install(mode="scripted")
    try:
        for host in ("localhost", "127.0.0.1", "::1"):
            with pytest.raises(OSError, match="11434"):
                socket.getaddrinfo(host, 11434)
        with socket.socket() as sock, pytest.raises(OSError, match=r"127\.0\.0\.1:11434"):
            sock.connect(("127.0.0.1", 11434))
    finally:
        uninstall()


def test_restore_keeps_later_patches_and_stale_wrappers_pass_through(no_network: None) -> None:
    install(mode="replay")
    guard_wrapper = socket.getaddrinfo
    later = lambda *args, **kwargs: _no_real_network(*args, **kwargs)  # noqa: E731
    socket.getaddrinfo = later  # type: ignore[assignment]
    uninstall()
    assert socket.getaddrinfo is later  # a patch made after install() is kept
    socket.getaddrinfo = guard_wrapper  # a monkeypatch undoing itself after uninstall()
    try:
        assert guard_wrapper("localhost", 80)  # inactive: passes straight through
        with pytest.raises(AssertionError, match="reached the real resolver"):
            guard_wrapper("api.openai.com", 443)  # not refused by the stale guard
    finally:
        socket.getaddrinfo = _no_real_network  # type: ignore[assignment]


def test_uninstall_restores_the_socket_functions(no_network: None) -> None:
    before = (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex)
    install(mode="replay")
    assert socket.getaddrinfo is not before[0]
    assert socket.socket.connect is not before[1]
    uninstall()
    assert (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex) == before
    assert guarded_hosts() == ()


def test_no_guard_in_modes_that_call_the_real_api(
    no_network: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_upstream(monkeypatch)
    install(mode="live")
    try:
        assert guarded_hosts() == ()
        assert socket.socket.connect is _no_real_connect  # untouched by install()
    finally:
        uninstall()


def test_invalid_guard_hosts_leave_nothing_installed(
    no_network: None, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "wardenbot.toml").write_text('[model]\nguard_hosts = ["host:notaport"]\n')
    monkeypatch.setenv("WARDENBOT_CONFIG", str(tmp_path / "wardenbot.toml"))
    with pytest.raises(ModelEndpointError, match="Invalid egress guard host"):
        install(mode="replay")
    assert "OPENAI_BASE_URL" not in os.environ
    assert guarded_hosts() == ()


@pytest.mark.parametrize(
    ("entry", "host", "port"),
    [
        ("API.OpenAI.com.", "api.openai.com", None),
        ("llm.internal:8443", "llm.internal", 8443),
        ("api.example.com/v1", "api.example.com", None),
        ("https://gw.example/v1", "gw.example", None),
        ("https://gw.example:8443/v1", "gw.example", 8443),
        ("http://127.0.0.1/v1", "127.0.0.1", 80),
        ("https://localhost/v1", "localhost", 443),
        ("localhost:11434/v1", "localhost", 11434),
        ("[::1]:8000", "::1", 8000),
        ("10.0.0.5", "10.0.0.5", None),
    ],
)
def test_parse_guarded(entry: str, host: str, port: int | None) -> None:
    parsed = parse_guarded(entry)
    assert (parsed[0].host, parsed[0].port) == (host, port) or any(
        (guarded.host, guarded.port) == (host, port) for guarded in parsed
    )
    if host in {"localhost", "127.0.0.1", "::1"}:
        assert {guarded.host for guarded in parsed} == {"localhost", "127.0.0.1", "::1"}


def test_parse_guarded_rejects_bad_entries() -> None:
    with pytest.raises(ValueError, match="No host"):
        parse_guarded("file:///tmp/x")
    with pytest.raises(ValueError, match="host:notaport"):
        parse_guarded("host:notaport")


def _guard_survives_fork(queue: Any) -> None:
    from pytest_wardenbot.model._guard import guarded_hosts

    before = len(guarded_hosts())
    uninstall()  # a forked child removes the inherited guard
    queue.put((before, len(guarded_hosts()), socket.getaddrinfo is _no_real_network))


@pytest.mark.skipif(
    "fork" not in __import__("multiprocessing").get_all_start_methods(), reason="needs fork"
)
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_a_forked_child_can_remove_the_inherited_guard(guarded: Endpoint) -> None:
    import multiprocessing

    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_guard_survives_fork, args=(queue,))
    process.start()
    before, after, restored = queue.get(timeout=30)
    process.join(timeout=30)
    assert before > 0 and after == 0 and restored


def test_real_sdk_client_with_explicit_base_url_trips_the_guard(guarded: Endpoint) -> None:
    openai = pytest.importorskip("openai")
    client = openai.OpenAI(base_url="https://api.openai.com/v1", api_key="unused", max_retries=0)
    with (
        pytest.raises(EgressBlockedError, match=r"api\.openai\.com"),
        model_endpoint("sdk-bypass", script="x"),
        pytest.raises(openai.APIConnectionError),
    ):
        client.responses.create(model="gpt-x", input="hi")
