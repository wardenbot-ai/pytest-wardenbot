"""Pinned actions and hash-locked tool requirements stay pinned and in sync."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = [
    *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ROOT / "examples" / "github_actions" / "wardenbot.yml",
]
LOCKS = sorted((ROOT / "requirements").glob("*.txt"))
_USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)(.*)$", re.M)
_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _pins(lock: Path) -> dict[str, str]:
    text = lock.read_text(encoding="utf-8")
    return {
        canonicalize_name(name): version
        for name, version in re.findall(r"^([A-Za-z0-9][\w.-]*)==([^\s;\\]+)", text, re.M)
    }


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_commit_sha_with_its_version(workflow):
    uses = _USES.findall(workflow.read_text(encoding="utf-8"))
    assert uses, f"{workflow.name} uses no actions"
    for action, comment in uses:
        if action.startswith("./"):
            continue
        assert _PIN.match(action), f"{workflow.name}: {action} is not pinned to a commit SHA"
        assert re.search(r"#\s*v\d", comment), f"{workflow.name}: {action} has no version comment"


@pytest.mark.parametrize("lock", LOCKS, ids=lambda path: path.name)
def test_tool_locks_pin_every_package_with_hashes(lock):
    text = lock.read_text(encoding="utf-8")
    entries = re.split(r"\n(?=[A-Za-z0-9])", text.split("\n", 2)[2])
    assert entries
    for entry in entries:
        if entry.strip():
            assert "==" in entry and "--hash=sha256:" in entry, entry.splitlines()[0]


def test_docs_lock_satisfies_the_docs_extra():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    pins = _pins(ROOT / "requirements" / "docs.txt")
    for line in project["optional-dependencies"]["docs"] + project["dependencies"]:
        requirement = Requirement(line)
        name = canonicalize_name(requirement.name)
        assert name in pins, f"{name} is missing from requirements/docs.txt"
        assert requirement.specifier.contains(pins[name], prereleases=True), (
            f"requirements/docs.txt pins {name}=={pins[name]}, outside {requirement}; "
            "regenerate it with the command in its header"
        )


def test_tool_locks_match_their_inputs():
    for lock in LOCKS:
        source = lock.with_suffix(".in")
        if not source.exists():
            continue
        pins = _pins(lock)
        for line in source.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                requirement = Requirement(line)
                name = canonicalize_name(requirement.name)
                assert requirement.specifier.contains(pins.get(name, "0")), (
                    f"{lock.name} does not satisfy {line}; regenerate it"
                )
