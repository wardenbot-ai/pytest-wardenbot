"""The model endpoint: a local OpenAI-compatible HTTP server, one per process.

``install()`` starts it before the application is imported and points the
OpenAI SDK at it through ``OPENAI_BASE_URL``. Each ``model_endpoint(...)``
block then only switches the active case, its replies and its capture buffer.
The URL never changes, so clients the application built at import time, or
cached, keep working.
"""

from __future__ import annotations

import atexit
import json
import os
import threading
import warnings
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._cases import current_case, running_test_id
from pytest_wardenbot.model._config import (
    Settings,
    load_callable,
    refuse_in_ci,
    resolve_settings,
)
from pytest_wardenbot.model._errors import ModelEndpointError
from pytest_wardenbot.model._folder import LookupState, ReplayMissError, ResponseFolder
from pytest_wardenbot.model._guard import (
    DEFAULT_GUARDED,
    EgressBlockedError,
    install_guard,
    uninstall_guard,
)
from pytest_wardenbot.model._reply import Reply
from pytest_wardenbot.model._script import Script, ScriptCursor
from pytest_wardenbot.model._wire import JSON_TYPE, Ids, error_body, render

MOCK_API_KEY = "wardenbot-mock"  # pragma: allowlist secret
"""The dummy ``OPENAI_API_KEY`` the endpoint sets. It is never sent anywhere."""

ENDPOINT_ENV = "WARDENBOT_ENDPOINT"
ORIGINAL_BASE_URL_ENV = "WARDENBOT_ORIGINAL_OPENAI_BASE_URL"
ORIGINAL_API_KEY_ENV = "WARDENBOT_ORIGINAL_OPENAI_API_KEY"  # pragma: allowlist secret
_PROXY_VARIABLES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
_TOUCHED = (
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "NO_PROXY",
    "no_proxy",
    ENDPOINT_ENV,
    ORIGINAL_BASE_URL_ENV,
    ORIGINAL_API_KEY_ENV,
)
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
_GUARDED_MODES = frozenset({"scripted", "replay"})
_KEEP_OUTSIDE = 1000
"""How many requests and errors from outside any block an endpoint keeps."""
_EXIT_WAIT_SECONDS = 5.0
"""How long a block's exit waits for its requests still being served."""

_lock = threading.RLock()
_endpoint: Endpoint | None = None
_atexit_registered = False


class Endpoint:
    """The process's model endpoint, returned by ``install()``.

    ``url`` is the base URL to give clients that don't read ``OPENAI_BASE_URL``
    (it ends in ``/v1``); it is None when the mode is ``off``. Requests made
    inside a ``model_endpoint`` block belong to that block. ``request_count``
    counts every request since ``install()``; ``requests`` and ``errors`` hold
    the most recent requests and errors from outside any block (up to 1,000
    each), including errors from a block's requests that finished after the
    block exited.
    """

    def __init__(self, settings: Settings, *, cli: tuple[Any, Any, Path | None]) -> None:
        self.settings = settings
        self.pid = os.getpid()
        self.url: str | None = None
        self.request_count = 0
        self.error_count = 0
        self._cli = cli
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._saved_env: dict[str, str | None] = {}
        self._state = threading.Condition()
        self._blocks: list[EndpointCase] = []
        self._requests: deque[CapturedRequest] = deque(maxlen=_KEEP_OUTSIDE)
        self._errors: deque[ModelEndpointError] = deque(maxlen=_KEEP_OUTSIDE)
        self._outside_calls = 0
        self._outside_lookup = LookupState()
        self._folder: ResponseFolder | None = None
        self._folder_lock = threading.Lock()

    def __repr__(self) -> str:
        return f"Endpoint(mode={self.mode!r}, url={self.url!r})"

    @property
    def mode(self) -> str:
        """The process's global mode."""
        return self.settings.mode

    @property
    def enabled(self) -> bool:
        """False when the mode is ``off``: no server runs and nothing was changed."""
        return self.mode != "off"

    @property
    def responses_dir(self) -> Path | None:
        """The response folder, if one is configured."""
        return self.settings.responses_dir

    @property
    def requests(self) -> list[CapturedRequest]:
        """Recent requests made outside any ``model_endpoint`` block, in arrival order."""
        with self._state:
            return list(self._requests)

    @property
    def errors(self) -> list[ModelEndpointError]:
        """Recent errors from outside any block, or from a block that had already exited."""
        with self._state:
            return list(self._errors)

    # Server lifecycle -----------------------------------------------------

    def _start(self) -> None:
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "wardenbot-model-endpoint"

            def do_GET(self) -> None:
                status, data = endpoint._handle_get(self.path)
                self._send(status, JSON_TYPE, data)

            def do_POST(self) -> None:
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    length = -1
                if length < 0:
                    data = endpoint._reject(400, "The request has no valid Content-Length.")
                    self._send(400, JSON_TYPE, data)
                    return
                status, content_type, data = endpoint._handle_post(
                    self.path, self.rfile.read(length)
                )
                self._send(status, content_type, data)

            def do_PUT(self) -> None:
                self._send(405, JSON_TYPE, endpoint._reject(405, f"PUT {self.path}"))

            do_DELETE = do_PATCH = do_PUT

            def _send(self, status: int, content_type: str, data: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                if status >= 400:
                    # The OpenAI SDK retries 5xx responses unless told not to; a
                    # retry would repeat a replay miss or skip a scripted reply.
                    self.send_header("x-should-retry", "false")
                if not content_type.startswith("text/event-stream"):
                    self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        host, port = server.server_address[:2]
        self.url = f"http://{host}:{port}/v1"
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.05},
            daemon=True,
            name="wardenbot-model-endpoint",
        )
        self._thread.start()

    def _stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None

    # Blocks ---------------------------------------------------------------

    def _push(self, block: EndpointCase) -> None:
        with self._state:
            self._blocks.append(block)

    def _pop(self, block: EndpointCase) -> None:
        """Deactivate ``block``, waiting briefly for its requests still being served."""
        with self._state:
            if block in self._blocks:
                self._blocks.remove(block)
            self._state.wait_for(lambda: block._inflight == 0, timeout=_EXIT_WAIT_SECONDS)
            block._closed = True

    # Requests -------------------------------------------------------------

    def _active_block(self) -> EndpointCase | None:
        with self._state:
            return self._blocks[-1] if self._blocks else None

    def _reject(self, status: int, message: str) -> bytes:
        """Record a request the endpoint can't serve, so its block fails, and build the error."""
        if status == 405:
            message = f"The model endpoint does not serve {message}."
        self._record(self._active_block(), ModelEndpointError(message))
        return error_body(message)

    def _handle_get(self, path: str) -> tuple[int, bytes]:
        route = path.split("?", 1)[0].rstrip("/")
        model = {"id": "wardenbot-mock", "object": "model", "created": 0, "owned_by": "wardenbot"}
        if route.endswith("/v1/models"):
            return 200, json.dumps({"object": "list", "data": [model]}).encode()
        prefix, _, name = route.rpartition("/")
        if prefix.endswith("/v1/models") and name:
            return 200, json.dumps({**model, "id": name}).encode()
        return 404, self._reject(404, f"The model endpoint does not serve GET {route}.")

    def _handle_post(self, path: str, raw: bytes) -> tuple[int, str, bytes]:
        try:
            body = json.loads(raw or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return 400, JSON_TYPE, self._reject(400, f"The request body is not valid JSON: {error}")
        if not isinstance(body, dict):
            return 400, JSON_TYPE, self._reject(400, "The request body must be a JSON object.")

        request = CapturedRequest.from_body("POST", path, body)
        if request.api == "other":
            message = f"The model endpoint does not serve POST {request.path}."
            return 404, JSON_TYPE, self._reject(404, message)
        with self._state:
            block = self._blocks[-1] if self._blocks else None
            self.request_count += 1
            if block is not None:
                block._requests.append(request)
                block._inflight += 1
                number = len(block._requests)
            else:
                self._requests.append(request)
                self._outside_calls += 1
                number = self._outside_calls
        try:
            reply = self._reply_for(block, request)
            content_type, data = render(
                reply, request, ids=Ids.for_call(block.case if block else None, number)
            )
            return 200, content_type, data
        except ModelEndpointError as error:
            self._record(block, error)
            return 500, JSON_TYPE, error_body(str(error))
        except Exception as error:  # a bug here must still fail the test, not hang it
            wrapped = ModelEndpointError(
                f"The model endpoint failed on a request to {request.path}: "
                f"{type(error).__name__}: {error}"
            )
            self._record(block, wrapped)
            return 500, JSON_TYPE, error_body(str(wrapped))
        finally:
            if block is not None:
                with self._state:
                    block._inflight -= 1
                    self._state.notify_all()

    def _record_egress(self, error: EgressBlockedError) -> None:
        """Called by the egress guard, on the application's thread."""
        if self.pid != os.getpid():
            return  # a forked child: this copy of the endpoint has no server and no reader
        self._record(self._active_block(), error)

    def _record(self, block: EndpointCase | None, error: ModelEndpointError) -> None:
        with self._state:
            if block is None:
                self._errors.append(error)
                self.error_count += 1
            elif block._closed:
                # The block already exited and can no longer raise; keep the error visible.
                late = ModelEndpointError(f"After case {block.case!r} exited: {error}")
                self._errors.append(late)
                self.error_count += 1
            else:
                block._errors.append(error)

    def response_folder(self) -> ResponseFolder | None:
        """The response folder, built on first use; its normalizers import then."""
        if self.responses_dir is None:
            return None
        # Not under _state: importing a normalizer can make the application send a
        # request, whose handler needs _state.
        with self._folder_lock:
            if self._folder is None:
                from pytest_wardenbot.model._hash import RequestHasher

                config = self.settings.config
                try:
                    normalizers = [load_callable(name) for name in config.normalizers]
                except WardenBotConfigError as error:
                    raise ModelEndpointError(f"In {config.source}: {error}") from None
                hasher = RequestHasher(config.ignore_fields, normalizers)
                self._folder = ResponseFolder(self.responses_dir, hasher)
            return self._folder

    def _reply_for(self, block: EndpointCase | None, request: CapturedRequest) -> Reply:
        if block is not None and block._cursor is not None:
            return block._cursor.next(request)
        where = f"case {block.case!r}" if block is not None else "a request outside any block"
        if self.mode == "scripted":
            raise ModelEndpointError(
                f"The wardenbot model mode is 'scripted', so every case must pass script=, "
                f"but {where} has none (request to {request.path})."
            )
        if self.mode == "replay":
            folder = self.response_folder()
            if folder is None:
                raise ReplayMissError(
                    f"The wardenbot model mode is 'replay', but no response folder is "
                    f"configured, so {where} has no reply (request to {request.path}). Set "
                    "responses_dir in [tool.wardenbot.model], WARDENBOT_RESPONSES_DIR or "
                    "--wardenbot-responses-dir."
                )
            if block is None:
                # Stateless outside blocks, so results don't depend on test order.
                return folder.find(request, None, LookupState())
            return folder.find(request, block.case, block._lookup, test_id=block.test_id)
        raise ModelEndpointError(
            f"The wardenbot model mode {self.mode!r} can't answer {where} yet "
            f"(request to {request.path}): pass script=."
        )


class EndpointCase:
    """One ``model_endpoint(...)`` block: its case, replies and captured requests.

    Use it as a context manager. On exit it raises the first error the endpoint
    hit while serving the block's requests, so a missing reply fails the test
    even when the application catches the HTTP error. If the block's body is
    already raising, the endpoint's errors are added to that exception as notes.
    """

    def __init__(
        self, endpoint: Endpoint, case: str, script: Script | None, canary: str | None = None
    ) -> None:
        self._endpoint = endpoint
        self.case = case
        self.script = script
        self.canary = canary
        self.test_id = running_test_id()
        self._lookup = LookupState()
        self._cursor: ScriptCursor | None = script.cursor(case) if script is not None else None
        self._requests: list[CapturedRequest] = []
        self._errors: list[ModelEndpointError] = []
        self._entered = False
        self._inflight = 0
        self._closed = False

    def __repr__(self) -> str:
        return f"EndpointCase(case={self.case!r}, mode={self.mode!r})"

    @property
    def mode(self) -> str:
        """``scripted`` when the block passed ``script=``, else the global mode."""
        return "scripted" if self.script is not None else self._endpoint.mode

    @property
    def url(self) -> str | None:
        """The endpoint's base URL."""
        return self._endpoint.url

    @property
    def requests(self) -> list[CapturedRequest]:
        """The requests captured in this block, in arrival order."""
        with self._endpoint._state:
            return list(self._requests)

    @property
    def errors(self) -> list[ModelEndpointError]:
        """Errors the endpoint hit while serving this block."""
        with self._endpoint._state:
            return list(self._errors)

    def __enter__(self) -> EndpointCase:
        if self._entered:
            raise ModelEndpointError("A model_endpoint block can only be entered once.")
        self._entered = True
        self._endpoint._push(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._endpoint._pop(self)
        errors = self.errors
        if not errors:
            return
        summary = _summarize(self.case, errors)
        if exc is not None:
            exc.add_note(summary)
            return
        # Keep the specific class (such as EgressBlockedError) when every error shares it.
        kinds = {type(error) for error in errors}
        kind = kinds.pop() if len(kinds) == 1 else ModelEndpointError
        raise kind(summary) from errors[0]


def _summarize(case: str, errors: list[ModelEndpointError]) -> str:
    if len(errors) == 1:
        return f"Model endpoint error in case {case!r}: {errors[0]}"
    lines = [f"{len(errors)} model endpoint errors in case {case!r}:"]
    lines += [f"  {number}. {error}" for number, error in enumerate(errors, 1)]
    return "\n".join(lines)


def _handoff_environment(endpoint: Endpoint) -> None:
    """Point the OpenAI SDK at the endpoint, keeping the originals for children and upstream."""
    assert endpoint.url is not None
    env = os.environ
    endpoint._saved_env = {key: env.get(key) for key in _TOUCHED}
    inherited = env.get(ENDPOINT_ENV, "")
    if not inherited:
        env[ORIGINAL_BASE_URL_ENV] = env.get("OPENAI_BASE_URL", "")
        env[ORIGINAL_API_KEY_ENV] = env.get("OPENAI_API_KEY", "")
    else:
        # A child of a process that installed an endpoint. Its OPENAI_* values
        # point at the parent's endpoint and must never become an upstream.
        parent_url = inherited.partition(" ")[2]
        if ORIGINAL_BASE_URL_ENV not in env:
            base = env.get("OPENAI_BASE_URL", "")
            env[ORIGINAL_BASE_URL_ENV] = "" if base == parent_url else base
        if ORIGINAL_API_KEY_ENV not in env:
            key = env.get("OPENAI_API_KEY", "")
            env[ORIGINAL_API_KEY_ENV] = "" if key == MOCK_API_KEY else key
    env["OPENAI_BASE_URL"] = endpoint.url
    env["OPENAI_API_KEY"] = MOCK_API_KEY
    for name in ("NO_PROXY", "no_proxy"):
        hosts = [host.strip() for host in env.get(name, "").split(",") if host.strip()]
        hosts += [host for host in _LOOPBACK_HOSTS if host not in hosts]
        env[name] = ",".join(hosts)
    env[ENDPOINT_ENV] = f"{endpoint.pid} {endpoint.url}"


def _restore_environment(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _warn_about_proxies() -> None:
    present = [
        name
        for variable in _PROXY_VARIABLES
        for name in (variable, variable.lower())
        if os.environ.get(name, "").strip()
    ]
    if present:
        warnings.warn(
            f"{', '.join(present)} is set. The wardenbot model endpoint is exempt through "
            "NO_PROXY, but a client that bypasses it sends its traffic to the proxy, where the "
            "egress guard can't see it.",
            UserWarning,
            stacklevel=3,
        )


def _shutdown_at_exit() -> None:
    endpoint = _endpoint
    if endpoint is not None and endpoint.enabled and endpoint.pid == os.getpid():
        uninstall_guard()
        endpoint._stop()


def _install_guard(endpoint: Endpoint) -> None:
    """Guard the model API hosts a client could reach by bypassing the endpoint."""
    server = endpoint._server
    assert server is not None
    host, port = server.server_address[:2]
    hosts = [*DEFAULT_GUARDED, *endpoint.settings.config.guard_hosts]
    original = os.environ.get(ORIGINAL_BASE_URL_ENV, "").strip()
    if original:
        hosts.append(original)
    try:
        install_guard(hosts, allowed=(str(host), int(port)), on_block=endpoint._record_egress)
    except ValueError as error:
        raise ModelEndpointError(f"Invalid egress guard host: {error}") from None


def install(
    *,
    mode: str | None = None,
    responses_dir: str | os.PathLike[str] | None = None,
    _cli_mode: str | None = None,
    _cli_responses_dir: str | os.PathLike[str] | None = None,
    _start: Path | None = None,
    _explicit: bool = True,
    _settings: Settings | None = None,
) -> Endpoint:
    """Start the process's model endpoint and point the OpenAI SDK at it.

    Call it before the application is imported: under pytest the plugin does,
    in Django call it at the top of the test settings module, and elsewhere
    before importing the application. It is idempotent and returns the same
    ``Endpoint`` every time in a process.

    ``mode`` and ``responses_dir`` are defaults: ``WARDENBOT_MODEL_MODE`` and
    ``WARDENBOT_RESPONSES_DIR`` outrank them, and they outrank the config file.
    With no mode set anywhere, an explicit ``install()`` means ``replay``. In
    mode ``off`` it changes nothing and returns a disabled endpoint.

    Otherwise it saves the original ``OPENAI_BASE_URL`` and ``OPENAI_API_KEY`` as
    ``WARDENBOT_ORIGINAL_OPENAI_BASE_URL`` and ``WARDENBOT_ORIGINAL_OPENAI_API_KEY``,
    then sets ``OPENAI_BASE_URL`` to the endpoint, ``OPENAI_API_KEY`` to the dummy
    ``wardenbot-mock``, adds the loopback hosts to ``NO_PROXY``, and records its
    pid and URL in ``WARDENBOT_ENDPOINT``. A child process that inherits these
    starts its own endpoint when it calls ``install()``, and keeps the
    originals as its upstream.

    In ``scripted`` and ``replay`` it also installs the egress guard, which
    refuses ``api.openai.com``, the original ``OPENAI_BASE_URL`` host and the
    configured ``guard_hosts``, so a client that bypasses the endpoint fails
    loudly instead of reaching the real API.
    """
    global _endpoint, _atexit_registered
    with _lock:
        existing = _endpoint
        if existing is not None and existing.pid == os.getpid():
            _check_compatible(existing, mode, responses_dir, _cli_mode, _cli_responses_dir)
            return existing
        if existing is not None:
            uninstall_guard()  # a forked child: drop the parent's guard before installing anew
        settings = _settings or resolve_settings(
            cli_mode=_cli_mode,
            cli_responses_dir=_cli_responses_dir,
            code_mode=mode,
            code_responses_dir=responses_dir,
            start=_start,
            installing=_explicit,
        )
        endpoint = Endpoint(settings, cli=(_cli_mode, _cli_responses_dir, _start))
        if endpoint.enabled:
            refuse_in_ci(settings.mode)
            _warn_about_proxies()  # before any change, in case warnings are errors
            endpoint._start()
            try:
                _handoff_environment(endpoint)
                if settings.mode in _GUARDED_MODES:
                    _install_guard(endpoint)
            except BaseException:
                # Leave nothing half-installed: no server, guard or rewritten environment.
                uninstall_guard()
                endpoint._stop()
                _restore_environment(endpoint._saved_env)
                raise
            if not _atexit_registered:
                atexit.register(_shutdown_at_exit)
                _atexit_registered = True
        _endpoint = endpoint
        return endpoint


def _check_compatible(
    endpoint: Endpoint,
    mode: str | None,
    responses_dir: str | os.PathLike[str] | None,
    cli_mode: str | None = None,
    cli_responses_dir: str | os.PathLike[str] | None = None,
) -> None:
    """Refuse a second ``install()`` whose arguments would resolve to different settings."""
    if mode is None and responses_dir is None and cli_mode is None and cli_responses_dir is None:
        return
    installed_cli_mode, installed_cli_responses_dir, start = endpoint._cli
    wanted = resolve_settings(
        cli_mode=cli_mode if cli_mode is not None else installed_cli_mode,
        cli_responses_dir=(
            cli_responses_dir if cli_responses_dir is not None else installed_cli_responses_dir
        ),
        code_mode=mode,
        code_responses_dir=responses_dir,
        start=start,
        installing=True,
        config=endpoint.settings.config,
    )
    if (wanted.mode, wanted.responses_dir) != (endpoint.mode, endpoint.responses_dir):
        raise ModelEndpointError(
            "The wardenbot model endpoint is already installed in this process with "
            f"mode={endpoint.mode!r} and responses_dir={endpoint.responses_dir}, so a request "
            f"for mode={wanted.mode!r} and responses_dir={wanted.responses_dir} can't take "
            "effect. "
            "The endpoint starts once per process, before the application is imported: "
            "choose the mode and folder there, or with WARDENBOT_MODEL_MODE and "
            "WARDENBOT_RESPONSES_DIR."
        )


def uninstall() -> None:
    """Stop the endpoint and restore the environment ``install()`` changed."""
    global _endpoint
    with _lock:
        endpoint, _endpoint = _endpoint, None
    if endpoint is None or not endpoint.enabled:
        return
    uninstall_guard()  # also in a forked child, which inherited the guard
    if endpoint.pid != os.getpid():
        return
    endpoint._stop()
    _restore_environment(endpoint._saved_env)


def current_endpoint() -> Endpoint | None:
    """The endpoint ``install()`` returned in this process, if any."""
    return _endpoint


def _active_endpoint(script: object) -> Endpoint:
    endpoint = _endpoint
    if endpoint is None:
        raise ModelEndpointError(
            "The wardenbot model endpoint isn't installed. Call "
            "pytest_wardenbot.model.install() before the application is imported; under "
            "pytest the plugin does this when [tool.wardenbot.model] is configured or "
            "--wardenbot-model-mode is given."
        )
    if endpoint.pid != os.getpid():
        raise ModelEndpointError(
            "This process was forked from the one that installed the wardenbot model "
            "endpoint. The endpoint's server thread doesn't survive a fork, and clients built "
            "before it still talk to the parent, so requests would be captured in the wrong "
            "process. Fork-based parallel runners aren't supported (for example Django's "
            "--parallel on Linux with Python 3.13 or earlier): use the spawn or forkserver "
            "start method, pytest-xdist, or run these tests serially."
        )
    if not endpoint.enabled:
        if script is not None:
            raise ModelEndpointError(
                "script= needs the model endpoint, but the wardenbot model mode is 'off'. Set "
                "the mode to 'scripted' or 'replay' (WARDENBOT_MODEL_MODE, "
                "--wardenbot-model-mode or [tool.wardenbot.model])."
            )
        raise ModelEndpointError("The wardenbot model mode is 'off', so there is no endpoint.")
    return endpoint


def model_endpoint(
    case: str | None = None, *, script: Any = None, canary: str | None = None
) -> EndpointCase:
    """Open a block that serves one case's model requests.

    ``case`` names the case; it defaults to the running test's id. Passing the
    same name from two tests lets them share replies. ``script`` makes the case
    scripted whatever the global mode: it takes anything ``Script.coerce``
    accepts. Without it, the case follows the global mode. ``canary`` is a canary
    configured elsewhere, such as the ``wardenbot_canary`` fixture, that
    ``case_canary()`` returns for this case instead of a derived one.

    The block yields an ``EndpointCase`` whose ``requests`` are the requests the
    application sent inside it. Blocks nest; the innermost one is active.
    """
    endpoint = _active_endpoint(script)
    if canary is not None and not isinstance(canary, str):
        raise TypeError(f"canary must be a string, not {type(canary).__name__}.")
    if script is None:
        refuse_in_ci(endpoint.mode)
    return EndpointCase(
        endpoint,
        current_case(case),
        Script.coerce(script) if script is not None else None,
        canary=canary.strip() or None if canary is not None else None,
    )
