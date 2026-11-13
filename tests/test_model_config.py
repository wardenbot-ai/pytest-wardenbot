"""Config discovery, mode precedence and the CI check for the model endpoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pytest_wardenbot._errors import WardenBotConfigError
from pytest_wardenbot.model._config import (
    MODES,
    ModelConfig,
    find_config_file,
    in_ci,
    load_callable,
    load_config,
    refuse_in_ci,
    resolve_settings,
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_no_config_means_off(tmp_path: Path) -> None:
    settings = resolve_settings(start=tmp_path, environ={})
    assert settings.mode == "off"
    assert settings.responses_dir is None
    assert not settings.config.configured


def test_explicit_install_defaults_to_replay(tmp_path: Path) -> None:
    assert resolve_settings(start=tmp_path, environ={}, installing=True).mode == "replay"


def test_pyproject_table_enables_replay_and_resolves_paths(tmp_path: Path) -> None:
    write(
        tmp_path / "pyproject.toml",
        '[project]\nname = "app"\n\n[tool.wardenbot.model]\nresponses_dir = "tests/llm"\n'
        'guard_hosts = ["llm.internal"]\nignore_fields = ["user"]\n'
        'normalizers = ["app.tests:strip_ids"]\n',
    )
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    settings = resolve_settings(start=nested, environ={})
    assert settings.mode == "replay"
    assert settings.responses_dir == (tmp_path / "tests" / "llm").resolve()
    assert settings.config.source == (tmp_path / "pyproject.toml").resolve()
    assert settings.config.guard_hosts == ("llm.internal",)
    assert settings.config.ignore_fields == ("user",)
    assert settings.config.normalizers == ("app.tests:strip_ids",)


def test_pyproject_without_table_does_not_count(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", '[project]\nname = "app"\n')
    assert find_config_file(tmp_path, environ={}) is None
    assert resolve_settings(start=tmp_path, environ={}).mode == "off"


def test_wardenbot_toml_wins_and_accepts_both_table_names(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nmode = "scripted"\n')
    write(tmp_path / "wardenbot.toml", '[model]\nmode = "live"\n')
    assert load_config(tmp_path, environ={}).mode == "live"
    write(tmp_path / "wardenbot.toml", '[tool.wardenbot.model]\nmode = "record"\n')
    assert load_config(tmp_path, environ={}).mode == "record"


def test_discovery_stops_at_the_project_root(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nmode = "live"\n')
    project = tmp_path / "project"
    write(project / "pyproject.toml", '[project]\nname = "app"\n')
    assert load_config(project / "src", environ={}).configured is False
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert load_config(repo, environ={}).configured is False
    # A wardenbot.toml at the root still counts, and so does one below it.
    write(project / "wardenbot.toml", '[model]\nmode = "scripted"\n')
    assert load_config(project / "src", environ={}).mode == "scripted"


def test_unreadable_ancestor_outside_the_project_is_never_read(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", "[not valid toml\n")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    assert load_config(project, environ={}).configured is False


def test_nearest_directory_wins(tmp_path: Path) -> None:
    write(tmp_path / "wardenbot.toml", '[model]\nmode = "live"\n')
    inner = tmp_path / "inner"
    write(inner / "wardenbot.toml", '[model]\nmode = "scripted"\n')
    assert load_config(inner, environ={}).mode == "scripted"


def test_wardenbot_config_env_names_the_file(tmp_path: Path) -> None:
    other = write(tmp_path / "elsewhere" / "custom.toml", '[tool.wardenbot.model]\nmode = "live"\n')
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nmode = "scripted"\n')
    config = load_config(tmp_path, environ={"WARDENBOT_CONFIG": str(other)})
    assert config.mode == "live"
    assert config.source == other.resolve()


@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        ("missing.toml", None, "is not a file"),
        ("pyproject.toml", '[project]\nname = "x"\n', "no [tool.wardenbot.model] table"),
        ("wardenbot.toml", "[other]\n", "no [model] table"),
    ],
)
def test_wardenbot_config_env_errors(
    tmp_path: Path, name: str, text: str | None, message: str
) -> None:
    path = tmp_path / name
    if text is not None:
        write(path, text)
    with pytest.raises(WardenBotConfigError, match=message.replace("[", r"\[")):
        load_config(tmp_path, environ={"WARDENBOT_CONFIG": str(path)})


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ('respones_dir = "x"', r"unknown wardenbot model setting\(s\) 'respones_dir'"),
        ('mode = "fast"', "Unknown wardenbot model mode 'fast'"),
        ("mode = 3", "`mode` must be a string"),
        ("responses_dir = 3", "`responses_dir` must be a non-empty string"),
        ('responses_dir = ""', "`responses_dir` must be a non-empty string"),
        ('normalizers = [".relative:f"]', "must look like 'package.module:function'"),
        ('normalizers = ["pkg:"]', "must look like 'package.module:function'"),
        ('guard_hosts = "api.example"', "`guard_hosts` must be a list of strings"),
        ('normalizers = ["no_colon"]', "must look like 'package.module:function'"),
    ],
)
def test_invalid_config_names_the_file(tmp_path: Path, table: str, message: str) -> None:
    path = write(tmp_path / "pyproject.toml", f"[tool.wardenbot.model]\n{table}\n")
    with pytest.raises(WardenBotConfigError, match=message) as error:
        load_config(tmp_path, environ={})
    assert str(path.resolve()) in str(error.value)


@pytest.mark.parametrize("text", ["tool = 1\n", '[tool]\nwardenbot = "x"\n'])
def test_non_table_tool_keys_are_ignored(tmp_path: Path, text: str) -> None:
    write(tmp_path / "pyproject.toml", text)
    assert load_config(tmp_path, environ={}).configured is False


def test_responses_dir_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nresponses_dir = "~/fixtures"\n')
    assert load_config(tmp_path, environ={}).responses_dir == (tmp_path / "home" / "fixtures")


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    write(tmp_path / "wardenbot.toml", "[model\n")
    with pytest.raises(WardenBotConfigError, match="is not valid TOML"):
        load_config(tmp_path, environ={})


def test_model_table_must_be_a_table(tmp_path: Path) -> None:
    write(tmp_path / "wardenbot.toml", 'model = "replay"\n')
    with pytest.raises(WardenBotConfigError, match="must be a table"):
        load_config(tmp_path, environ={})


@pytest.mark.parametrize(
    ("cli", "env", "file", "expected"),
    [
        ("record", "scripted", "live", "record"),
        (None, "scripted", "live", "scripted"),
        (None, None, "live", "live"),
        ("live", None, "scripted", "live"),
        (None, "live", "scripted", "live"),
        ("", "", "scripted", "scripted"),
        (" Replay ", None, None, "replay"),
    ],
)
def test_mode_precedence_both_directions(
    tmp_path: Path, cli: str | None, env: str | None, file: str | None, expected: str
) -> None:
    table = f'mode = "{file}"\n' if file else ""
    write(tmp_path / "pyproject.toml", f"[tool.wardenbot.model]\n{table}")
    environ = {} if env is None else {"WARDENBOT_MODEL_MODE": env}
    assert resolve_settings(cli_mode=cli, start=tmp_path, environ=environ).mode == expected


def test_install_arguments_sit_between_environment_and_file(tmp_path: Path) -> None:
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nmode = "live"\n')
    assert resolve_settings(code_mode="scripted", start=tmp_path, environ={}).mode == "scripted"
    env = {"WARDENBOT_MODEL_MODE": "record"}
    assert resolve_settings(code_mode="scripted", start=tmp_path, environ=env).mode == "record"
    chosen = resolve_settings(cli_mode="replay", code_mode="scripted", start=tmp_path, environ=env)
    assert chosen.mode == "replay"
    directory = resolve_settings(code_responses_dir=tmp_path / "code", start=tmp_path, environ={})
    assert directory.responses_dir == tmp_path / "code"


def test_bad_mode_names_its_source(tmp_path: Path) -> None:
    with pytest.raises(WardenBotConfigError, match="'nope' from WARDENBOT_MODEL_MODE"):
        resolve_settings(start=tmp_path, environ={"WARDENBOT_MODEL_MODE": "nope"})
    with pytest.raises(WardenBotConfigError, match="from --wardenbot-model-mode"):
        resolve_settings(cli_mode="nope", start=tmp_path, environ={})


def test_responses_dir_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path / "pyproject.toml", '[tool.wardenbot.model]\nresponses_dir = "from_file"\n')
    monkeypatch.chdir(tmp_path)
    env = {"WARDENBOT_RESPONSES_DIR": "from_env"}
    assert resolve_settings(start=tmp_path, environ={}).responses_dir == tmp_path / "from_file"
    assert resolve_settings(start=tmp_path, environ=env).responses_dir == tmp_path / "from_env"
    chosen = resolve_settings(cli_responses_dir="from_cli", start=tmp_path, environ=env)
    assert chosen.responses_dir == tmp_path / "from_cli"


def test_a_given_config_skips_discovery(tmp_path: Path) -> None:
    config = ModelConfig(source=tmp_path / "x.toml", mode="scripted")
    assert resolve_settings(config=config, environ={}).mode == "scripted"


def test_load_callable_wraps_import_time_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "broken_normalizer.py", "raise RuntimeError('boom at import')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(WardenBotConfigError, match="RuntimeError: boom at import"):
        load_callable("broken_normalizer:f")


def test_load_callable(tmp_path: Path) -> None:
    assert load_callable("os.path:join") is __import__("os").path.join
    assert load_callable("os:path.join") is __import__("os").path.join
    for name, message in [
        ("nocolon", "must look like"),
        (".relative:f", "must look like"),
        ("no_such_module_xyz:f", "Cannot import"),
        ("os:no_such_attr", "has no attribute"),
        ("os:sep", "is not callable"),
    ]:
        with pytest.raises(WardenBotConfigError, match=message):
            load_callable(name)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("FALSE", False),
        ("no", False),
        (" no ", False),
        ("true", True),
        ("1", True),
        ("yes", True),
        ("github-actions", True),
        ("off", False),
    ],
)
def test_in_ci(value: str | None, expected: bool) -> None:
    assert in_ci({} if value is None else {"CI": value}) is expected


@pytest.mark.parametrize(
    "name", ["JENKINS_URL", "TF_BUILD", "TEAMCITY_VERSION", "BUILDKITE", "CODEBUILD_BUILD_ID"]
)
def test_ci_services_without_ci_variable(name: str) -> None:
    assert in_ci({name: "x"})
    assert not in_ci({name: ""})
    with pytest.raises(WardenBotConfigError, match=f"{name} is set"):
        refuse_in_ci("record", environ={name: "x"})


@pytest.mark.parametrize("mode", MODES)
def test_refuse_in_ci(mode: str) -> None:
    refuse_in_ci(mode, environ={})
    if mode in {"override", "record", "live"}:
        with pytest.raises(WardenBotConfigError, match=f"mode '{mode}' calls the real model API"):
            refuse_in_ci(mode, environ={"CI": "true"})
    else:
        refuse_in_ci(mode, environ={"CI": "true"})


def test_model_package_does_not_import_pytest() -> None:
    code = (
        "import sys, pytest_wardenbot.model, pytest_wardenbot.model._config, "
        "pytest_wardenbot.model._cases; "
        "print(sorted(m for m in ('pytest', '_pytest') if m in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"
