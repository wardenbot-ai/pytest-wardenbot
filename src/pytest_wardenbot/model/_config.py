"""Configuration for the model endpoint: config file, mode and the CI check.

Settings come from three places, in order of precedence: a value passed in by
the runner (the pytest CLI options), the ``WARDENBOT_*`` environment variables,
and a config file. The config file is the ``[tool.wardenbot.model]`` table of a
``pyproject.toml``, or the ``[model]`` table of a ``wardenbot.toml``, read with
the standard library so no test runner is needed to find it.
"""

from __future__ import annotations

import importlib
import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pytest_wardenbot._errors import WardenBotConfigError

MODES = ("off", "scripted", "replay", "override", "record", "live")
"""Every endpoint mode, from no endpoint at all to every request going to the real API."""

UPSTREAM_MODES = frozenset({"override", "record", "live"})
"""Modes that call the real model API. They refuse to run in CI."""

CONFIG_KEYS = ("mode", "responses_dir", "guard_hosts", "ignore_fields", "normalizers")

CONFIG_ENV = "WARDENBOT_CONFIG"
MODE_ENV = "WARDENBOT_MODEL_MODE"
RESPONSES_DIR_ENV = "WARDENBOT_RESPONSES_DIR"
MODE_OPTION = "--wardenbot-model-mode"
RESPONSES_DIR_OPTION = "--wardenbot-responses-dir"

_FALSE_CI_VALUES = frozenset({"", "0", "false", "no"})


@dataclass(frozen=True)
class ModelConfig:
    """The model table of a config file, with paths resolved against the file's directory.

    ``source`` is None when no config file enables the feature.
    """

    source: Path | None = None
    mode: str | None = None
    responses_dir: Path | None = None
    guard_hosts: tuple[str, ...] = ()
    ignore_fields: tuple[str, ...] = ()
    normalizers: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return self.source is not None


@dataclass(frozen=True)
class Settings:
    """The effective settings after precedence: runner, then environment, then file."""

    mode: str
    responses_dir: Path | None
    config: ModelConfig


def _table(data: Mapping[str, Any], path: Path) -> Mapping[str, Any] | None:
    """Return the model table of a parsed config file, or None if it has none."""
    nested = data.get("tool", {}).get("wardenbot", {}).get("model")
    if path.name == "wardenbot.toml" and nested is None:
        nested = data.get("model")
    if nested is not None and not isinstance(nested, Mapping):
        raise WardenBotConfigError(f"{path}: the wardenbot model settings must be a table.")
    return nested


def _read(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as error:
        raise WardenBotConfigError(f"Cannot read the wardenbot config {path}: {error}") from None
    except tomllib.TOMLDecodeError as error:
        raise WardenBotConfigError(f"{path} is not valid TOML: {error}") from None


def find_config_file(
    start: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> tuple[Path, Mapping[str, Any]] | None:
    """Locate the config file and its model table.

    ``WARDENBOT_CONFIG`` names a file directly. Otherwise each directory from
    ``start`` (default: the working directory) up to the filesystem root is
    searched; in each, ``wardenbot.toml`` wins over ``pyproject.toml``. A file
    counts only if it has a model table.
    """
    env = os.environ if environ is None else environ
    named = env.get(CONFIG_ENV, "").strip()
    if named:
        path = Path(named).expanduser().resolve()
        if not path.is_file():
            raise WardenBotConfigError(f"{CONFIG_ENV} names {path}, which is not a file.")
        table = _table(_read(path), path)
        if table is None:
            expected = "[model]" if path.name == "wardenbot.toml" else "[tool.wardenbot.model]"
            raise WardenBotConfigError(f"{CONFIG_ENV} names {path}, which has no {expected} table.")
        return path, table

    directory = (start or Path.cwd()).resolve()
    for folder in (directory, *directory.parents):
        for name in ("wardenbot.toml", "pyproject.toml"):
            path = folder / name
            if path.is_file():
                table = _table(_read(path), path)
                if table is not None:
                    return path, table
    return None


def _strings(value: Any, key: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise WardenBotConfigError(f"{path}: `{key}` must be a list of strings.")
    return tuple(value)


def validate_mode(value: str, source: str) -> str:
    """Return the normalized mode, or raise naming where the bad value came from."""
    mode = value.strip().lower()
    if mode not in MODES:
        raise WardenBotConfigError(
            f"Unknown wardenbot model mode {value!r} from {source}. Use one of: {', '.join(MODES)}."
        )
    return mode


def load_config(
    start: Path | None = None, *, environ: Mapping[str, str] | None = None
) -> ModelConfig:
    """Read and validate the model table of the config file, if there is one."""
    found = find_config_file(start, environ=environ)
    if found is None:
        return ModelConfig()
    path, table = found
    unknown = sorted(set(table) - set(CONFIG_KEYS))
    if unknown:
        raise WardenBotConfigError(
            f"{path}: unknown wardenbot model setting(s) {', '.join(map(repr, unknown))}. "
            f"Valid settings: {', '.join(CONFIG_KEYS)}."
        )
    mode = table.get("mode")
    if mode is not None:
        if not isinstance(mode, str):
            raise WardenBotConfigError(f"{path}: `mode` must be a string.")
        mode = validate_mode(mode, str(path))
    responses_dir = table.get("responses_dir")
    if responses_dir is not None and not isinstance(responses_dir, str):
        raise WardenBotConfigError(f"{path}: `responses_dir` must be a string.")
    normalizers = _strings(table.get("normalizers", []), "normalizers", path)
    for name in normalizers:
        module, _, attribute = name.partition(":")
        if not module or not attribute:
            raise WardenBotConfigError(
                f"{path}: normalizer {name!r} must look like 'package.module:function'."
            )
    return ModelConfig(
        source=path,
        mode=mode,
        responses_dir=(path.parent / responses_dir).resolve() if responses_dir else None,
        guard_hosts=_strings(table.get("guard_hosts", []), "guard_hosts", path),
        ignore_fields=_strings(table.get("ignore_fields", []), "ignore_fields", path),
        normalizers=normalizers,
    )


def resolve_settings(
    *,
    cli_mode: str | None = None,
    cli_responses_dir: str | os.PathLike[str] | None = None,
    start: Path | None = None,
    installing: bool = False,
    environ: Mapping[str, str] | None = None,
    config: ModelConfig | None = None,
) -> Settings:
    """Apply precedence: the runner's value, then the environment, then the config file.

    With nothing set, the mode is ``replay`` when a config file enables the
    feature or ``install()`` is called explicitly (``installing``), else ``off``.
    """
    env = os.environ if environ is None else environ
    config = load_config(start, environ=env) if config is None else config

    mode: str | None = None
    for source, value in (
        (MODE_OPTION, cli_mode),
        (MODE_ENV, env.get(MODE_ENV)),
        (str(config.source), config.mode),
    ):
        if value is not None and value.strip():
            mode = validate_mode(value, source)
            break
    if mode is None:
        mode = "replay" if config.configured or installing else "off"

    responses_dir: Path | None = None
    for value in (cli_responses_dir, env.get(RESPONSES_DIR_ENV)):
        if value is not None and str(value).strip():
            responses_dir = Path(value).expanduser().resolve()
            break
    else:
        responses_dir = config.responses_dir

    return Settings(mode=mode, responses_dir=responses_dir, config=config)


def load_callable(name: str) -> Callable[..., Any]:
    """Import ``package.module:attribute`` and return it; it must be callable."""
    module_name, _, attribute = name.partition(":")
    if not module_name or not attribute:
        raise WardenBotConfigError(f"{name!r} must look like 'package.module:function'.")
    try:
        target: Any = importlib.import_module(module_name)
    except ImportError as error:
        raise WardenBotConfigError(f"Cannot import {module_name!r} for {name!r}: {error}") from None
    for part in attribute.split("."):
        try:
            target = getattr(target, part)
        except AttributeError:
            raise WardenBotConfigError(f"{module_name!r} has no attribute {attribute!r}.") from None
    if not callable(target):
        raise WardenBotConfigError(f"{name!r} is not callable.")
    return target


def in_ci(environ: Mapping[str, str] | None = None) -> bool:
    """True when the ``CI`` environment variable is set to a true-looking value."""
    env = os.environ if environ is None else environ
    value = env.get("CI")
    return value is not None and value.strip().lower() not in _FALSE_CI_VALUES


def refuse_in_ci(mode: str, *, environ: Mapping[str, str] | None = None) -> None:
    """Raise if ``mode`` would call the real model API while running in CI."""
    env = os.environ if environ is None else environ
    if mode in UPSTREAM_MODES and in_ci(env):
        raise WardenBotConfigError(
            f"The wardenbot model mode {mode!r} calls the real model API, so it refuses to "
            f"run in CI (CI={env.get('CI')!r}). Use 'replay' or 'scripted' in CI, and "
            f"'{mode}' only on a developer machine."
        )
