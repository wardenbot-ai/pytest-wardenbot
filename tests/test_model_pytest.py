"""The pytest layer over the model endpoint: early install, options, marker and fixture.

Each run is a separate pytest process, because install() changes the process
environment exactly as it would in a user's run.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import textwrap
from pathlib import Path

import pytest

from tests.model_support import ENDPOINT_VARIABLES

pytest_plugins = ["pytester"]
HAS_OPENAI = importlib.util.find_spec("openai") is not None
HAS_XDIST = importlib.util.find_spec("xdist") is not None
SCRIPTED = ["-p", "no:cacheprovider", "--wardenbot-model-mode=scripted"]


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*ENDPOINT_VARIABLES, "CI", "GITHUB_ACTIONS", "JENKINS_URL", "TF_BUILD"):
        monkeypatch.delenv(name, raising=False)


def test_not_configured_changes_nothing(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import os, threading
        def test_untouched():
            assert "OPENAI_BASE_URL" not in os.environ
            assert "WARDENBOT_ENDPOINT" not in os.environ
            names = [thread.name for thread in threading.enumerate()]
            assert "wardenbot-model-endpoint" not in names
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert "wardenbot model endpoint" not in result.stdout.str()


def test_cli_mode_installs_before_conftest_imports(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(
        """
        import os
        SEEN_AT_IMPORT = os.environ.get("OPENAI_BASE_URL", "")
        """
    )
    pytester.makepyfile(
        """
        import os
        from conftest import SEEN_AT_IMPORT
        from pytest_wardenbot.model import model_endpoint

        def test_endpoint_was_there_first():
            assert SEEN_AT_IMPORT.startswith("http://127.0.0.1:")
            assert os.environ["OPENAI_API_KEY"] == "wardenbot-mock"
            with model_endpoint(script="hi") as block:
                assert block.mode == "scripted"
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*wardenbot model endpoint*", "mode=scripted, 0 requests"])


@pytest.mark.skipif(not HAS_OPENAI, reason="needs the openai extra")
def test_client_built_at_import_time_and_cached_across_tests(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        pipeline=(
            "import openai\n"
            "CLIENT = openai.OpenAI(max_retries=0)\n"
            "def summarize(text):\n"
            "    return CLIENT.responses.create(model='gpt-x', input=text).output_text\n"
        )
    )
    pytester.makeconftest("import pipeline  # builds the client while conftest.py loads\n")
    pytester.makepyfile(
        test_pipeline="""
        import pytest
        import pipeline

        @pytest.mark.wardenbot_model(script="first reply")
        def test_first(wardenbot_model):
            assert pipeline.summarize("one") == "first reply"
            assert wardenbot_model.requests[0].text("user") == "one"

        @pytest.mark.wardenbot_model(script="second reply")
        def test_second(wardenbot_model):
            assert pipeline.summarize("two") == "second reply"
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED)
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["mode=scripted, 2 requests"])


@pytest.mark.parametrize(
    ("cli", "env", "file", "expected"),
    [
        ("scripted", "replay", "replay", "scripted"),
        (None, "scripted", "replay", "scripted"),
        (None, None, "scripted", "scripted"),
        (None, None, None, "replay"),
        ("replay", "scripted", "scripted", "replay"),
    ],
)
def test_mode_selection_end_to_end(
    pytester: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
    cli: str | None,
    env: str | None,
    file: str | None,
    expected: str,
) -> None:
    table = f'mode = "{file}"\n' if file else ""
    pytester.makepyprojecttoml(f"[tool.wardenbot.model]\n{table}")
    if env:
        monkeypatch.setenv("WARDENBOT_MODEL_MODE", env)
    pytester.makepyfile(
        f"""
        from pytest_wardenbot.model._endpoint import current_endpoint

        def test_mode():
            assert current_endpoint().mode == {expected!r}
        """
    )
    args = ["-p", "no:cacheprovider", *([f"--wardenbot-model-mode={cli}"] if cli else [])]
    pytester.runpytest_subprocess(*args).assert_outcomes(passed=1)


def test_responses_dir_option(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        from pathlib import Path
        from pytest_wardenbot.model._endpoint import current_endpoint

        def test_folder():
            assert current_endpoint().responses_dir == Path.cwd() / "replies"
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED, "--wardenbot-responses-dir=replies")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["mode=scripted, folder=*replies, 0 requests"])


def test_marker_and_fixture(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import pytest

        def test_default_case_is_the_node_id(wardenbot_model, request):
            assert wardenbot_model.case == request.node.nodeid
            assert wardenbot_model.mode == "scripted"

        @pytest.mark.wardenbot_model(case="shared_case", script="x")
        def test_explicit_case(wardenbot_model):
            assert wardenbot_model.case == "shared_case"

        @pytest.mark.wardenbot_model("positional")
        def test_positional_marker_arguments(wardenbot_model):
            pass
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED, "--strict-markers")
    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(["*takes keyword arguments only*"])


def test_endpoint_errors_fail_at_teardown(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import os, httpx, pytest

        @pytest.mark.wardenbot_model(script="only one")
        def test_two_requests(wardenbot_model):
            base = os.environ["OPENAI_BASE_URL"]
            for _ in range(2):
                httpx.post(base + "/responses", json={"input": "x"})  # errors swallowed
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED)
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*has 1 reply, and this was request 2*"])


def test_fixture_fails_clearly_when_the_feature_is_off(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        def test_needs_endpoint(wardenbot_model):
            pass
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*model endpoint isn't installed*"])


def test_requests_outside_blocks_are_reported(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import os, httpx

        def test_stray_request():
            httpx.post(os.environ["OPENAI_BASE_URL"] + "/responses", json={"input": "x"})
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED)
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(
        ["outside any model_endpoint block: *every case must pass script=*"]
    )


def test_config_errors_are_usage_errors(pytester: pytest.Pytester) -> None:
    pytester.makepyprojecttoml('[tool.wardenbot.model]\nmode = "sometimes"\n')
    pytester.makepyfile("def test_x():\n    pass\n")
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*Unknown wardenbot model mode 'sometimes'*"])


def test_upstream_modes_refuse_ci(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CI", "true")
    pytester.makepyfile("def test_x():\n    pass\n")
    result = pytester.runpytest_subprocess(
        "-p", "no:cacheprovider", "--wardenbot-model-mode=record"
    )
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*mode 'record' calls the real model API*refuses to run in CI*"])


@pytest.mark.skipif(not HAS_XDIST, reason="needs pytest-xdist")
def test_each_xdist_worker_gets_its_own_endpoint(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
        import os, pytest

        @pytest.mark.parametrize("n", range(4))
        def test_report(n, tmp_path_factory):
            out = tmp_path_factory.getbasetemp().parent.parent / f"endpoint-{os.getpid()}"
            out.write_text(os.environ["WARDENBOT_ENDPOINT"])
        """
    )
    result = pytester.runpytest_subprocess(*SCRIPTED, "-n", "2")
    result.assert_outcomes(passed=4)
    reports = {}
    for path in Path(pytester.path).rglob("endpoint-*"):
        reports[path.name] = path.read_text()
    if len(reports) < 2:
        pytest.skip("xdist ran every test on one worker")
    pids = {value.split()[0] for value in reports.values()}
    urls = {value.split()[1] for value in reports.values()}
    assert len(pids) == len(reports) and len(urls) == len(reports)
    assert str(os.getpid()) not in pids


def test_model_plugin_uses_no_private_pytest_api() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "pytest_wardenbot" / "_model_plugin.py"
    private = [
        node.attr
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.Attribute)
        and node.attr.startswith("_")
        and not node.attr.startswith("__")
    ]
    assert private == []


def test_options_are_documented_in_help(pytester: pytest.Pytester) -> None:
    result = pytester.runpytest_subprocess("--help")
    text = textwrap.dedent(result.stdout.str())
    assert "--wardenbot-model-mode" in text and "--wardenbot-responses-dir" in text
