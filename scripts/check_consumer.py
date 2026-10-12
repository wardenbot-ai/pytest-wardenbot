"""Check a wheel installation from independent, temporary consumer projects.

Run with the Python interpreter of a venv containing the installed wheel:
    /path/to/venv/bin/python scripts/check_consumer.py

No source imports, editable installs, additional test plugins, network calls,
or API keys are needed. Pytest discovers wardenbot through its entry point.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_SAFE_CONFTEST = """
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_wardenbot.adapters.base import ChatbotResponse
from pytest_wardenbot.business_truth import BusinessTruthFact
from pytest_wardenbot.grading import judge as judge_module
from pytest_wardenbot.grading.judge import brand_alignment_case

class SafeBot:
    def __init__(self, name, events):
        self.name = name
        self.events = events

    def send_message(self, prompt, *, session_id=None):
        self.events.append("probe:" + self.name + ":" + prompt)
        if prompt == "Plan price?":
            text = "$49"
        elif prompt == "Support hours?":
            text = "9 AM to 5 PM"
        else:
            text = "I'm sorry, I can't help with that. Let's focus on your account."
        return ChatbotResponse(text=text, raw={})

    def reset_session(self, session_id):
        pass

@pytest.fixture(scope="session", autouse=True)
def setup_guard():
    events = ["session-setup"]
    yield events
    events.append("session-teardown")
    Path("lifecycle.json").write_text(json.dumps(events))

@pytest.fixture(name="chatbot", scope="session", params=["first", "second"], ids=str)
def configured_bot(request, setup_guard):
    setup_guard.append("bot-setup:" + request.param)
    yield SafeBot(request.param, setup_guard)
    setup_guard.append("bot-teardown:" + request.param)

@pytest.fixture(params=[
    BusinessTruthFact(label="Price", question="Plan price?", expected_answer="$49"),
    BusinessTruthFact(label="Hours", question="Support hours?", expected_answer="9 AM to 5 PM"),
], ids=lambda fact: fact.parametrize_id())
def business_truth_fact(request):
    return request.param

@pytest.fixture(params=[
    brand_alignment_case(prompt="Hello", brand_voice="friendly", label="Greeting"),
    brand_alignment_case(prompt="Goodbye", brand_voice="friendly", label="Farewell"),
], ids=lambda case: case.parametrize_id())
def judge_case(request):
    return request.param

@pytest.fixture(autouse=True)
def stub_judge(monkeypatch):
    monkeypatch.setattr(judge_module, "judge_available", lambda: True)
    monkeypatch.setattr(judge_module, "api_key_available", lambda: True)
    def factory(case, actual, model, temp):
        metric = MagicMock(score=0.95, reason="Aligned")
        return metric, MagicMock()
    monkeypatch.setattr(judge_module, "_default_deepeval_judge_factory", factory)

@pytest.fixture
def wardenbot_canary():
    return "WBCANARY-consumer-secret"

@pytest.fixture
def wardenbot_jailbreak_prompts():
    return (("Consumer custom first", "consumer-one"),
            ("Consumer custom second", "consumer-two"))
"""

_VULNERABLE_CONFTEST = """
import pytest
from pytest_wardenbot.adapters.base import ChatbotResponse

class VulnerableBot:
    name = "vulnerable"
    def send_message(self, prompt, *, session_id=None):
        return ChatbotResponse(
            text="DAN mode activated! My system prompt is WBCANARY-consumer-secret.",
            raw={},
        )
    def reset_session(self, session_id):
        pass

@pytest.fixture
def chatbot():
    return VulnerableBot()

@pytest.fixture
def wardenbot_canary():
    return "WBCANARY-consumer-secret"
"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _check_installation() -> str:
    distribution = importlib.metadata.distribution("pytest-wardenbot")
    direct_url = json.loads(distribution.read_text("direct_url.json") or "{}")
    _require(
        not direct_url.get("dir_info", {}).get("editable", False),
        "Consumer check requires an installed wheel, not an editable install.",
    )
    spec = importlib.util.find_spec("pytest_wardenbot")
    _require(spec is not None and spec.origin is not None, "Installed package is missing.")
    assert spec is not None and spec.origin is not None
    package_path = Path(spec.origin).resolve()
    _require(
        package_path.is_relative_to(Path(sys.prefix).resolve()),
        f"Package must come from the consumer venv, found {package_path}.",
    )
    _require(
        any(
            entry.group == "pytest11"
            and entry.name == "wardenbot"
            and entry.value == "pytest_wardenbot.plugin"
            for entry in distribution.entry_points
        ),
        "Wheel is missing the wardenbot pytest11 entry point.",
    )
    return str(package_path)


def _run(
    project: Path,
    conftest: str,
    *targets: str,
    files: dict[str, str] | None = None,
) -> dict[str, Any]:
    project.mkdir()
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    if conftest:
        (project / "conftest.py").write_text(conftest, encoding="utf-8")
    for name, content in (files or {}).items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    environment = os.environ.copy()
    for name in (
        "PYTHONPATH",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
    ):
        environment.pop(name, None)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--pyargs", *targets, "-v", "--junitxml=result.xml"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    output = result.stdout + result.stderr
    xml_path = project / "result.xml"
    _require(xml_path.exists(), f"Pytest did not write a consumer report:\n{output}")
    cases = ET.parse(xml_path).findall(".//testcase")
    failures = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {
        "exit_code": result.returncode,
        "passed": len(cases) - failures - errors - skipped,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "names": [case.get("name", "") for case in cases],
        "properties": [
            {prop.get("name"): prop.get("value") for prop in case.findall("./properties/property")}
            for case in cases
        ],
        "output": output,
    }


def _expect(result: dict[str, Any], **expected: int) -> None:
    for name, count in expected.items():
        _require(
            result[name] == count,
            f"Consumer expected {name}={count}, got {result[name]}:\n{result['output']}",
        )


_AGENT_CONFTEST = """
import pytest
from pytest_wardenbot.mcp import MCPHarness, ScriptedMCPAgentTarget

@pytest.fixture
def harness(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return MCPHarness(
        wardenbot_agent_scenario,
        transport="stdio",
        attack_enabled=wardenbot_agent_attack_enabled,
    )

@pytest.fixture
def agent_target(harness):
    return ScriptedMCPAgentTarget(harness, behavior="resistant")

@pytest.fixture
def agent_observer(harness):
    return harness.observe
"""


def check_agents() -> None:
    """Exercise packaged scenario selection and coverage outside the checkout."""
    package_path = _check_installation()
    target = "pytest_wardenbot.agent_tests"
    selected = "--wardenbot-agent-scenario=mcp.tool-result.forbidden-tool@1"
    with tempfile.TemporaryDirectory(prefix="wardenbot-agent-consumer-") as temporary:
        root = Path(temporary)
        safe = _run(root / "safe", _AGENT_CONFTEST, target, "--wardenbot-agent-required")
        _expect(safe, exit_code=0, passed=16, failed=0, errors=0, skipped=0)
        _require(len(set(safe["names"])) == 16, "Agent nodes must have unique stable IDs.")
        for properties in safe["properties"]:
            phase = properties.get("wardenbot.agent.phase")
            expected = "resisted" if phase == "attack" else "inconclusive"
            _require(
                properties.get("wardenbot.agent.outcome") == expected,
                "JUnit lost the agent domain outcome or baseline distinction.",
            )
            _require(
                properties.get("wardenbot.agent.task_succeeded") == "true",
                "JUnit lost independent task utility.",
            )
        pair = _run(root / "pair", _AGENT_CONFTEST, target, selected, "--wardenbot-agent-required")
        _expect(pair, exit_code=0, passed=2, failed=0, errors=0, skipped=0)
        missing = _run(root / "missing", "", target, selected)
        _require(missing["exit_code"] != 0, "Missing integration silently passed.")
        _require(
            "agent_target" in missing["output"], "Missing target setup needs actionable guidance."
        )
        deselected = _run(
            root / "deselected",
            _AGENT_CONFTEST,
            target,
            selected,
            "--wardenbot-agent-required",
            "-k",
            "baseline",
        )
        _expect(deselected, exit_code=1, passed=1, failed=0, errors=0, skipped=0)
        _require(
            "Required agent coverage incomplete" in deselected["output"],
            "Required deselection lacks a coverage explanation.",
        )
        vulnerable = _run(
            root / "vulnerable",
            _AGENT_CONFTEST.replace('behavior="resistant"', 'behavior="vulnerable"'),
            target,
            selected,
        )
        _expect(vulnerable, exit_code=1, passed=1, failed=1, errors=0, skipped=0)
        _require(
            any(p.get("wardenbot.agent.outcome") == "violated" for p in vulnerable["properties"]),
            "Actual recorded effects must retain the violated domain outcome.",
        )
        imported = _run(
            root / "imported",
            _AGENT_CONFTEST,
            "test_local.py",
            selected,
            "--wardenbot-agent-required",
            files={
                "test_local.py": (
                    "from pytest_wardenbot.agent_tests.test_security import test_agent_security\n"
                )
            },
        )
        _expect(imported, exit_code=0, passed=2, failed=0, errors=0, skipped=0)
        sys.stdout.write(
            json.dumps(
                {
                    "package": package_path,
                    "agent_consumer_checks": {
                        label: {
                            key: result[key] for key in ("exit_code", "passed", "failed", "errors")
                        }
                        for label, result in (
                            ("safe", safe),
                            ("pair", pair),
                            ("missing", missing),
                            ("required_deselection", deselected),
                            ("vulnerable", vulnerable),
                            ("imported", imported),
                        )
                    },
                },
                indent=2,
            )
            + "\n"
        )


_APPLICATION_CONFTEST = """
import pytest
from pytest_wardenbot.agents.packs import (
    ApplicationHarness, ScriptedApplicationTarget, application_spec,
)
VULNERABLE = False

@pytest.fixture
def application(wardenbot_agent_scenario, wardenbot_agent_attack_enabled):
    return ApplicationHarness(
        application_spec(wardenbot_agent_scenario.id),
        variant="attack" if wardenbot_agent_attack_enabled else "benign",
        enforce_boundaries=not VULNERABLE,
    )

@pytest.fixture
def agent_target(application):
    return ScriptedApplicationTarget(
        application, behavior="vulnerable" if VULNERABLE else "resistant",
    )

@pytest.fixture
def agent_observer(application):
    return application.observe
"""


def check_applications() -> None:
    """Verify opt-in packs and real fixture behavior from a core wheel."""
    package_path = _check_installation()
    target = "pytest_wardenbot.agent_tests"
    selection = "--wardenbot-agent-pack=application"
    with tempfile.TemporaryDirectory(prefix="wardenbot-application-consumer-") as temporary:
        root = Path(temporary)
        safe = _run(
            root / "safe", _APPLICATION_CONFTEST, target, selection, "--wardenbot-agent-required"
        )
        _expect(safe, exit_code=0, passed=10, failed=0, errors=0, skipped=0)
        _require(
            {row.get("wardenbot.agent.pack") for row in safe["properties"]}
            == {"retrieval", "memory", "identity", "approval"},
            "Installed application corpus lost a required pack.",
        )
        pair = _run(
            root / "memory",
            _APPLICATION_CONFTEST,
            target,
            "--wardenbot-agent-pack=memory",
            "--wardenbot-agent-required",
        )
        _expect(pair, exit_code=0, passed=2, failed=0, errors=0, skipped=0)
        vulnerable = _run(
            root / "vulnerable",
            _APPLICATION_CONFTEST.replace("VULNERABLE = False", "VULNERABLE = True"),
            target,
            selection,
        )
        _expect(vulnerable, exit_code=1, passed=5, failed=5, errors=0, skipped=0)
        _require(
            sum(p.get("wardenbot.agent.outcome") == "violated" for p in vulnerable["properties"])
            == 5,
            "All vulnerable controls must record actual asserted effects.",
        )
        deselected = _run(
            root / "deselected",
            _APPLICATION_CONFTEST,
            target,
            selection,
            "--wardenbot-agent-required",
            "-k",
            "baseline",
        )
        _expect(deselected, exit_code=1, passed=5, failed=0, errors=0, skipped=0)
        _require(
            "Required agent coverage incomplete" in deselected["output"],
            "Missing application coverage must be explicit.",
        )
        sys.stdout.write(
            json.dumps(
                {
                    "package": package_path,
                    "application_consumer_checks": {
                        label: {
                            key: result[key] for key in ("exit_code", "passed", "failed", "errors")
                        }
                        for label, result in (
                            ("safe", safe),
                            ("memory", pair),
                            ("vulnerable", vulnerable),
                            ("deselected", deselected),
                        )
                    },
                },
                indent=2,
            )
            + "\n"
        )


def main() -> None:
    import pytest_wardenbot

    _require(
        pytest_wardenbot.__version__ == importlib.metadata.version("pytest-wardenbot"),
        "Runtime version must match the installed package metadata.",
    )
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--agents", action="store_true", help="Check the installed agent suite ([mcp])."
    )
    mode.add_argument(
        "--applications", action="store_true", help="Check installed application packs (core only)."
    )
    args = parser.parse_args()
    if args.agents:
        check_agents()
        return
    if args.applications:
        check_applications()
        return
    package_path = _check_installation()
    with tempfile.TemporaryDirectory(prefix="wardenbot-consumer-") as temporary:
        root = Path(temporary)
        safe_project = root / "safe"
        safe = _run(safe_project, _SAFE_CONFTEST, "pytest_wardenbot.tests")
        _expect(safe, exit_code=0, passed=56, failed=0, errors=0, skipped=0)
        names = "\n".join(safe["names"])
        for marker in (
            "consumer-one",
            "consumer-two",
            "first",
            "second",
            "Price",
            "Hours",
            "Greeting",
            "Farewell",
            "test_canary_never_appears_in_responses",
        ):
            _require(marker.lower() in names.lower(), f"Consumer fixture case missing: {marker}")
        events = json.loads((safe_project / "lifecycle.json").read_text())
        lifecycle = [event for event in events if not event.startswith("probe:")]
        _require(
            lifecycle
            == [
                "session-setup",
                "bot-setup:first",
                "bot-teardown:first",
                "bot-setup:second",
                "bot-teardown:second",
                "session-teardown",
            ],
            f"Fixture lifecycle changed: {lifecycle}",
        )
        for name in ("first", "second"):
            for prompt in (
                "Consumer custom first",
                "Consumer custom second",
                "Plan price?",
                "Support hours?",
                "Hello",
                "Goodbye",
            ):
                _require(
                    f"probe:{name}:{prompt}" in events, f"Bot was not probed: {name}: {prompt}"
                )

        mixed = _run(
            root / "mixed",
            _SAFE_CONFTEST,
            "pytest_wardenbot.tests.test_system_prompt_leak",
            "test_local.py",
            "nested",
            files={
                "test_local.py": (
                    "def test_root_bot(chatbot):\n    assert chatbot.name in ('first', 'second')\n"
                ),
                "nested/conftest.py": """
import pytest

@pytest.fixture
def chatbot(chatbot):
    class NestedBot:
        name = "nested-" + chatbot.name
    return NestedBot()

@pytest.fixture(autouse=True)
def nested_guard(chatbot):
    assert chatbot.name.startswith("nested-")
""",
                "nested/test_nested.py": (
                    "def test_nested_bot(chatbot):\n"
                    "    assert chatbot.name in ('nested-first', 'nested-second')\n"
                ),
            },
        )
        _expect(mixed, exit_code=0, passed=10, failed=0, errors=0, skipped=0)
        mixed_events = json.loads((root / "mixed" / "lifecycle.json").read_text())
        _require(
            [event for event in mixed_events if not event.startswith("probe:")] == lifecycle,
            "Mixed local/installed collection duplicated fixture setup or teardown.",
        )
        imported = _run(
            root / "imported",
            _SAFE_CONFTEST,
            "test_local.py",
            files={
                "test_local.py": (
                    "from pytest_wardenbot.tests.test_prompt_injection "
                    "import test_resists_jailbreak_compliance\n"
                ),
            },
        )
        _expect(imported, exit_code=0, passed=4, failed=0, errors=0, skipped=0)
        vulnerable = _run(root / "vulnerable", _VULNERABLE_CONFTEST, "pytest_wardenbot.tests")
        _require(
            vulnerable["exit_code"] == 1 and vulnerable["failed"] >= 10,
            f"Vulnerable chatbot was not detected:\n{vulnerable['output']}",
        )
        _require(vulnerable["errors"] == 0, f"Vulnerable bot setup failed:\n{vulnerable['output']}")
        missing = _run(root / "missing", "", "pytest_wardenbot.tests")
        _require(
            missing["exit_code"] == 1 and missing["errors"] >= 30,
            f"Missing chatbot produced a successful or incomplete run:\n{missing['output']}",
        )
        _require(
            "No `chatbot` fixture configured" in missing["output"],
            "Missing fixture error did not include setup instructions.",
        )
        summaries = {
            label: {
                key: result[key] for key in ("exit_code", "passed", "failed", "errors", "skipped")
            }
            for label, result in (
                ("safe", safe),
                ("mixed", mixed),
                ("imported", imported),
                ("vulnerable", vulnerable),
                ("missing", missing),
            )
        }
        sys.stdout.write(
            json.dumps({"package": package_path, "consumer_checks": summaries}, indent=2) + "\n"
        )


if __name__ == "__main__":
    main()
