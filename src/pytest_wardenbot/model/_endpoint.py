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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType
from typing import Any

from pytest_wardenbot.model._capture import CapturedRequest
from pytest_wardenbot.model._cases import current_case
from pytest_wardenbot.model._config import Settings, refuse_in_ci, resolve_settings
from pytest_wardenbot.model._errors import ModelEndpointError
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

_lock = threading.RLock()
_endpoint: Endpoint | None = None
_atexit_registered = False


class Endpoint:
    """The process's model endpoint, returned by ``install()``.

    ``url`` is the base URL to give clients that don't read ``OPENAI_BASE_URL``
    (it ends in ``/v1``); it is None when the mode is ``off``. ``requests``
    holds every request captured since ``install()``, and ``errors`` the errors
    from requests that arrived outside any ``model_endpoint`` block.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.pid = os.getpid()
        self.url: str | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._saved_env: dict[str, str | None] = {}
        self._state = threading.Lock()
        self._blocks: list[EndpointCase] = []
        self._requests: list[CapturedRequest] = []
        self._errors: list[ModelEndpointError] = []
        self._outside_calls = 0

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
        """Every request captured since ``install()``, in arrival order."""
        with self._state:
            return list(self._requests)

    @property
    def errors(self) -> list[ModelEndpointError]:
        """Errors from requests made outside any ``model_endpoint`` block."""
        with self._state:
            return list(self._errors)

    # Server lifecycle -----------------------------------------------------

    def _start(self) -> None:
        endpoint = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "wardenbot-model-endpoint"

            def do_GET(self) -> None:
                path = self.path.split("?", 1)[0].rstrip("/")
                if path.endswith("/models"):
                    models = {
                        "object": "list",
                        "data": [
                            {
                                "id": "wardenbot-mock",
                                "object": "model",
                                "created": 0,
                                "owned_by": "wardenbot",
                            }
                        ],
                    }
                    self._send(200, JSON_TYPE, json.dumps(models).encode())
                else:
                    self._send(404, JSON_TYPE, error_body(f"No route for GET {self.path}"))

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                status, content_type, data = endpoint._handle_post(
                    self.path, self.rfile.read(length)
                )
                self._send(status, content_type, data)

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
        with self._state:
            if block in self._blocks:
                self._blocks.remove(block)

    # Requests -------------------------------------------------------------

    def _handle_post(self, path: str, raw: bytes) -> tuple[int, str, bytes]:
        try:
            body = json.loads(raw or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return 400, JSON_TYPE, error_body(f"The request body is not valid JSON: {error}")
        if not isinstance(body, dict):
            return 400, JSON_TYPE, error_body("The request body must be a JSON object.")

        request = CapturedRequest.from_body("POST", path, body)
        if request.api == "other":
            return (
                404,
                JSON_TYPE,
                error_body(f"The model endpoint does not serve POST {request.path}."),
            )
        with self._state:
            block = self._blocks[-1] if self._blocks else None
            self._requests.append(request)
            if block is not None:
                block._requests.append(request)
                number = len(block._requests)
            else:
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

    def _record(self, block: EndpointCase | None, error: ModelEndpointError) -> None:
        with self._state:
            (block._errors if block is not None else self._errors).append(error)

    def _reply_for(self, block: EndpointCase | None, request: CapturedRequest) -> Reply:
        if block is not None and block._cursor is not None:
            return block._cursor.next(request)
        where = f"case {block.case!r}" if block is not None else "a request outside any block"
        if self.mode == "scripted":
            raise ModelEndpointError(
                f"The wardenbot model mode is 'scripted', so every case must pass script=, "
                f"but {where} has none (request to {request.path})."
            )
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

    def __init__(self, endpoint: Endpoint, case: str, script: Script | None) -> None:
        self._endpoint = endpoint
        self.case = case
        self.script = script
        self._cursor: ScriptCursor | None = script.cursor(case) if script is not None else None
        self._requests: list[CapturedRequest] = []
        self._errors: list[ModelEndpointError] = []
        self._entered = False

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
        raise ModelEndpointError(summary) from errors[0]


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
        endpoint._stop()


def install(
    *,
    mode: str | None = None,
    responses_dir: str | os.PathLike[str] | None = None,
    _cli_mode: str | None = None,
    _cli_responses_dir: str | os.PathLike[str] | None = None,
    _start: Path | None = None,
    _explicit: bool = True,
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
    """
    global _endpoint, _atexit_registered
    with _lock:
        if _endpoint is not None and _endpoint.pid == os.getpid():
            return _endpoint
        settings = resolve_settings(
            cli_mode=_cli_mode,
            cli_responses_dir=_cli_responses_dir,
            code_mode=mode,
            code_responses_dir=responses_dir,
            start=_start,
            installing=_explicit,
        )
        endpoint = Endpoint(settings)
        if endpoint.enabled:
            refuse_in_ci(settings.mode)
            endpoint._start()
            _handoff_environment(endpoint)
            if not _atexit_registered:
                atexit.register(_shutdown_at_exit)
                _atexit_registered = True
            _warn_about_proxies()
        _endpoint = endpoint
        return endpoint


def uninstall() -> None:
    """Stop the endpoint and restore the environment ``install()`` changed."""
    global _endpoint
    with _lock:
        endpoint, _endpoint = _endpoint, None
    if endpoint is None or not endpoint.enabled or endpoint.pid != os.getpid():
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


def model_endpoint(case: str | None = None, *, script: Any = None) -> EndpointCase:
    """Open a block that serves one case's model requests.

    ``case`` names the case; it defaults to the running test's id. Passing the
    same name from two tests lets them share replies. ``script`` makes the case
    scripted whatever the global mode: it takes anything ``Script.coerce``
    accepts. Without it, the case follows the global mode.

    The block yields an ``EndpointCase`` whose ``requests`` are the requests the
    application sent inside it. Blocks nest; the innermost one is active.
    """
    endpoint = _active_endpoint(script)
    if script is None:
        refuse_in_ci(endpoint.mode)
    return EndpointCase(
        endpoint, current_case(case), Script.coerce(script) if script is not None else None
    )
