"""pytest wiring for the model endpoint: early install, options, marker and fixture.

The endpoint itself (``pytest_wardenbot.model``) never imports pytest. This
module is the thin layer on top: it calls ``install()`` before any
``conftest.py`` is imported, so application modules that build an SDK client
at import time already see ``OPENAI_BASE_URL``. It uses only public pytest API.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model import EndpointCase, ModelEndpointError, install, model_endpoint
from pytest_wardenbot.model._config import MODES, resolve_settings
from pytest_wardenbot.model._endpoint import current_endpoint

MARKER = (
    "wardenbot_model(script=None, case=None): run the test inside a model_endpoint block "
    "through the `wardenbot_model` fixture, with these arguments"
)


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
    cli_mode = getattr(namespace, "wardenbot_model_mode", None)
    cli_responses_dir = getattr(namespace, "wardenbot_responses_dir", None)
    try:
        settings = resolve_settings(
            cli_mode=cli_mode, cli_responses_dir=cli_responses_dir, start=early_config.rootpath
        )
        if settings.mode != "off":
            install(
                _cli_mode=cli_mode,
                _cli_responses_dir=cli_responses_dir,
                _start=early_config.rootpath,
                _explicit=False,
            )
    except WardenBotConfigError as error:
        raise pytest.UsageError(str(error)) from None


def configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", MARKER)


def terminal_summary(terminalreporter: Any) -> None:
    endpoint = current_endpoint()
    if endpoint is None or not endpoint.enabled:
        return
    folder = endpoint.responses_dir
    parts = [f"mode={endpoint.mode}", f"{endpoint.request_count} requests"]
    if folder is not None:
        parts.insert(1, f"folder={folder}")
    terminalreporter.write_sep("-", "wardenbot model endpoint")
    terminalreporter.write_line(", ".join(parts))
    for error in endpoint.errors:
        terminalreporter.write_line(f"outside any model_endpoint block: {error}", red=True)


@pytest.fixture
def wardenbot_model(request: pytest.FixtureRequest) -> Iterator[EndpointCase]:
    """Run the test inside a ``model_endpoint`` block named after the test.

    Arguments come from the ``wardenbot_model`` marker, for example
    ``@pytest.mark.wardenbot_model(script={"ratings": []})``. The case name
    defaults to the test's node id; pass ``case=`` to share replies between
    tests. The fixture yields the block, whose ``requests`` are the requests the
    application sent during the test. Endpoint errors, such as a replay miss,
    fail the test at teardown even if the application swallowed them.
    """
    marker = request.node.get_closest_marker("wardenbot_model")
    arguments: dict[str, Any] = dict(marker.kwargs) if marker is not None else {}
    if marker is not None and marker.args:
        raise pytest.UsageError("@pytest.mark.wardenbot_model takes keyword arguments only.")
    case = arguments.pop("case", None) or request.node.nodeid
    try:
        block = model_endpoint(case, **arguments)
    except ModelEndpointError as error:
        pytest.fail(str(error), pytrace=False)
    with block:
        yield block
