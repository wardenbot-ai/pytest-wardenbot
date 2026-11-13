"""pytest wiring for the model endpoint: early install, options, marker and fixture.

The endpoint itself (``pytest_wardenbot.model``) never imports pytest. This
module is the thin layer on top: it calls ``install()`` before any
``conftest.py`` is imported, so application modules that build an SDK client
at import time already see ``OPENAI_BASE_URL``. It uses only public pytest API.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from pytest_wardenbot._errors import WardenBotError
from pytest_wardenbot.model import Endpoint, EndpointCase, install, model_endpoint, uninstall
from pytest_wardenbot.model._config import MODES, resolve_settings
from pytest_wardenbot.model._endpoint import current_endpoint

MARKER = (
    "wardenbot_model(script=None, case=None): run the test inside a model_endpoint block "
    "through the `wardenbot_model` fixture, with these arguments"
)
WORKER_OUTPUT_KEY = "wardenbot_model"


@dataclass
class _Session:
    """What this pytest session knows about the model endpoint."""

    installed: Endpoint | None = None
    """The endpoint this session's hook installed, which it uninstalls at the end."""
    baseline_errors: int = 0
    baseline_requests: int = 0
    worker_requests: int = 0
    worker_errors: list[str] = field(default_factory=list)


_SESSION = pytest.StashKey[_Session]()


def _session(config: pytest.Config) -> _Session:
    state = config.stash.get(_SESSION, None)
    if state is None:
        state = config.stash[_SESSION] = _Session()
    return state


def add_options(group: pytest.OptionGroup) -> None:
    group.addoption(
        "--wardenbot-model-mode",
        choices=MODES,
        default=None,
        help=(
            "Mode of the local model endpoint for pipeline tests: off, scripted, replay, "
            "override, record or live. Outranks WARDENBOT_MODEL_MODE and "
            "[tool.wardenbot.model]. override, record and live call the real API and "
            "refuse to run in CI."
        ),
    )
    group.addoption(
        "--wardenbot-responses-dir",
        default=None,
        metavar="DIR",
        help=(
            "Response folder the model endpoint replays from and records into. Outranks "
            "WARDENBOT_RESPONSES_DIR and responses_dir in [tool.wardenbot.model]."
        ),
    )


def load_initial_conftests(early_config: pytest.Config) -> None:
    """Install the endpoint before conftest.py files and pytest-django's setup run."""
    namespace = early_config.known_args_namespace
    if getattr(namespace, "help", False) or getattr(namespace, "version", False):
        return  # keep --help and --version working with a broken config
    cli_mode = getattr(namespace, "wardenbot_model_mode", None)
    cli_responses_dir = getattr(namespace, "wardenbot_responses_dir", None)
    try:
        settings = resolve_settings(
            cli_mode=cli_mode, cli_responses_dir=cli_responses_dir, start=early_config.rootpath
        )
        if settings.mode == "off":
            return
        before = current_endpoint()
        endpoint = install(
            _cli_mode=cli_mode,
            _cli_responses_dir=cli_responses_dir,
            _start=early_config.rootpath,
            _explicit=False,
            _settings=settings,
        )
    except WardenBotError as error:
        raise pytest.UsageError(str(error)) from None
    if endpoint is not before:
        _session(early_config).installed = endpoint


def configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", MARKER)


def session_start(session: pytest.Session) -> None:
    endpoint = current_endpoint()
    if endpoint is not None and endpoint.enabled:
        state = _session(session.config)
        state.baseline_errors = endpoint.error_count
        state.baseline_requests = endpoint.request_count


def _new_errors(config: pytest.Config) -> list[str]:
    endpoint = current_endpoint()
    if endpoint is None or not endpoint.enabled:
        return []
    count = endpoint.error_count - _session(config).baseline_errors
    return [str(error) for error in endpoint.errors[-count:]] if count > 0 else []


def _new_requests(config: pytest.Config) -> int:
    endpoint = current_endpoint()
    if endpoint is None or not endpoint.enabled:
        return 0
    return endpoint.request_count - _session(config).baseline_requests


def session_finish(session: pytest.Session) -> None:
    """Fail the run on endpoint errors no test could raise, and report them from workers."""
    config = session.config
    errors = _new_errors(config)
    worker_output = getattr(config, "workeroutput", None)
    if worker_output is not None:  # a pytest-xdist worker reports to the controller
        worker_output[WORKER_OUTPUT_KEY] = {"requests": _new_requests(config), "errors": errors}
    errors += _session(config).worker_errors
    if errors and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def testnode_down(node: Any) -> None:
    """Collect a pytest-xdist worker's request count and errors on the controller."""
    report = getattr(node, "workeroutput", {}).get(WORKER_OUTPUT_KEY)
    if not report:
        return
    state = _session(node.config)
    state.worker_requests += int(report.get("requests", 0))
    state.worker_errors += [str(error) for error in report.get("errors", ())]


def terminal_summary(terminalreporter: Any) -> None:
    config = terminalreporter.config
    endpoint = current_endpoint()
    state = _session(config)
    if (endpoint is None or not endpoint.enabled) and not state.worker_requests:
        return
    parts = [f"{_new_requests(config) + state.worker_requests} requests"]
    if endpoint is not None and endpoint.enabled:
        parts.insert(0, f"mode={endpoint.mode}")
        if endpoint.responses_dir is not None:
            parts.insert(1, f"folder={endpoint.responses_dir}")
    terminalreporter.write_sep("-", "wardenbot model endpoint")
    terminalreporter.write_line(", ".join(parts))
    for error in _new_errors(config) + state.worker_errors:
        terminalreporter.write_line(f"model endpoint error: {error}", red=True)


def unconfigure(config: pytest.Config) -> None:
    """Uninstall the endpoint this session installed, so a later run starts clean."""
    installed = _session(config).installed
    if installed is not None and current_endpoint() is installed:
        uninstall()


@pytest.fixture
def wardenbot_model(request: pytest.FixtureRequest) -> Iterator[EndpointCase]:
    """Run the test inside a ``model_endpoint`` block named after the test.

    Arguments come from the ``wardenbot_model`` marker, for example
    ``@pytest.mark.wardenbot_model(script={"ratings": []})``. The case name
    defaults to the test's node id; pass ``case=`` to share replies between
    tests. The fixture yields the block, whose ``requests`` are the requests the
    application sent during the test. Endpoint errors, such as a replay miss,
    fail the test at teardown even if the application swallowed them. A canary
    from the ``wardenbot_canary`` fixture becomes the case's canary.
    """
    marker = request.node.get_closest_marker("wardenbot_model")
    if marker is not None and marker.args:
        pytest.fail("@pytest.mark.wardenbot_model takes keyword arguments only.", pytrace=False)
    arguments: dict[str, Any] = dict(marker.kwargs) if marker is not None else {}
    case = arguments.pop("case", request.node.nodeid)
    canary = request.getfixturevalue("wardenbot_canary")
    try:
        block = model_endpoint(case, canary=canary, **arguments)
    except (WardenBotError, TypeError, ValueError) as error:
        pytest.fail(f"wardenbot_model: {error}", pytrace=False)
    with block:
        yield block
