"""The public API, the stability policy, the API reference and the docs agree.

The stability policy lists the public modules. Every name a public module
exports must be documented, and every import the docs, README and examples
show must come from a public module's ``__all__``. Everything is read
statically, so modules whose optional dependencies are missing are covered too.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DOCS = ROOT / "docs"
SHIPPED_TEST_PACKAGES = ("pytest_wardenbot.tests", "pytest_wardenbot.agent_tests")
FENCE = re.compile(
    r"^(?P<indent>[ \t]*)```(?P<lang>[\w+-]*)[^\n]*\n(?P<body>.*?)^(?P=indent)```[ \t]*$",
    re.S | re.M,
)


def public_modules() -> list[str]:
    text = (DOCS / "reference" / "stability.md").read_text(encoding="utf-8")
    table = text[text.index("| Module |") : text.index("**Not public API:**")]
    return re.findall(r"^\| `(pytest_wardenbot[\w.]*)` \|", table, re.M)


PUBLIC = public_modules()


def module_path(module: str) -> Path:
    path = SRC / module.replace(".", "/")
    return path / "__init__.py" if path.is_dir() else path.with_suffix(".py")


@cache
def module_tree(module: str) -> ast.Module:
    return ast.parse(module_path(module).read_text(encoding="utf-8"))


@cache
def exported(module: str) -> tuple[str, ...] | None:
    for node in module_tree(module).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    return None


def _absolute(module: str, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.split(".")
    if module_path(module).name != "__init__.py":
        package = package[:-1]
    package = package[: len(package) - (node.level - 1)]
    return ".".join([*package, *([node.module] if node.module else [])])


def has_docstring(module: str, name: str) -> bool | None:
    """Follow imports to the definition; None if the name isn't defined anywhere."""
    body = module_tree(module).body
    for index, node in enumerate(body):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.name == name
        ):
            return bool(ast.get_docstring(node))
        targets: list[str] = []
        if isinstance(node, ast.Assign):
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if name in targets:
            following = body[index + 1] if index + 1 < len(body) else None
            return (
                isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            )
    for node in ast.walk(module_tree(module)):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    return has_docstring(_absolute(module, node), alias.name)
    return None


def documented_sources() -> list[tuple[str, str]]:
    sources = []
    for path in [ROOT / "README.md", *sorted(DOCS.rglob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        for match in FENCE.finditer(text):
            if match["lang"] in {"python", "py"}:
                indent = len(match["indent"])
                body = "\n".join(line[indent:] for line in match["body"].splitlines())
                line = text[: match.start()].count("\n") + 1
                sources.append((f"{path.relative_to(ROOT)}:{line}", body))
    for path in sorted((ROOT / "examples").rglob("*.py")):
        sources.append((str(path.relative_to(ROOT)), path.read_text(encoding="utf-8")))
    return sources


SOURCES = documented_sources()


def test_policy_lists_the_public_packages():
    assert "pytest_wardenbot" in PUBLIC
    assert {"pytest_wardenbot.agents", "pytest_wardenbot.mcp", "pytest_wardenbot.local"} <= set(
        PUBLIC
    )
    assert len(PUBLIC) == len(set(PUBLIC))


@pytest.mark.parametrize("module", PUBLIC)
def test_public_module_declares_and_documents_its_exports(module):
    names = exported(module)
    assert names, f"{module} is public but has no __all__"
    undocumented = [
        name
        for name in names
        if not name.startswith("__") and has_docstring(module, name) is not True
    ]
    assert not undocumented, f"{module} exports names without docstrings: {undocumented}"


@pytest.mark.parametrize(("where", "source"), SOURCES, ids=[where for where, _ in SOURCES])
def test_documented_code_imports_only_public_names(where, source):
    tree = ast.parse(source)  # Every Python block in the docs is valid Python.
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            problems += [
                alias.name
                for alias in node.names
                if alias.name.startswith("pytest_wardenbot") and alias.name not in PUBLIC
            ]
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(
            "pytest_wardenbot"
        ):
            continue
        module = node.module or ""
        if module.startswith(SHIPPED_TEST_PACKAGES):
            continue
        if module not in PUBLIC:
            problems.append(f"{module} is not a public module")
            continue
        names = exported(module) or ()
        problems += [
            f"{module}.{alias.name} is not in __all__"
            for alias in node.names
            # A public submodule imported from its package is public too.
            if alias.name not in names and f"{module}.{alias.name}" not in PUBLIC
        ]
    assert not problems, problems


def api_reference() -> tuple[set[str], list[str]]:
    """Names the API page renders, and any directive outside the public modules."""
    text = (DOCS / "reference" / "api.md").read_text(encoding="utf-8")
    rendered: set[str] = set()
    problems: list[str] = []
    for block in re.split(r"^(?=::: )", text, flags=re.M)[1:]:
        lines = block.splitlines()
        identifier = lines[0].removeprefix("::: ").strip()
        options = "\n".join(line for line in lines[1:] if line.startswith("    "))
        members = re.findall(r'"([\w]+)"', options) if "members:" in options else None
        if identifier in PUBLIC:
            names = exported(identifier) or ()
            listed = members if members is not None else list(names)
            problems += [f"{identifier}.{name}" for name in listed if name not in names]
            rendered.update(listed)
        else:
            module, _, name = identifier.rpartition(".")
            if module in PUBLIC and name in (exported(module) or ()):
                rendered.add(name)
            else:
                problems.append(identifier)
    return rendered, problems


def test_api_reference_renders_only_public_modules():
    _, problems = api_reference()
    assert not problems, f"API reference renders non-public objects: {problems}"


def test_api_reference_covers_every_public_name():
    rendered, _ = api_reference()
    public = {
        name for module in PUBLIC for name in exported(module) or () if not name.startswith("__")
    }
    assert sorted(public - rendered) == []


def test_package_ships_a_typing_marker():
    assert (SRC / "pytest_wardenbot" / "py.typed").is_file()
