"""Private local recording format, never a public report/export format."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pytest_wardenbot.agents.contracts import (
    AgentCapability,
    AgentEvent,
    AttackSurface,
    EventKind,
    EventProvenance,
    EventTrust,
    Scenario,
)


def scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    data = asdict(scenario)
    data["required_capabilities"] = sorted(scenario.required_capabilities)
    return data


def scenario_from_dict(data: dict[str, Any]) -> Scenario:
    return Scenario(
        **{
            **data,
            "surface": AttackSurface(data["surface"]),
            "required_capabilities": frozenset(
                AgentCapability(item) for item in data["required_capabilities"]
            ),
        }
    )


def event_from_dict(data: dict[str, Any]) -> AgentEvent:
    return AgentEvent(
        **{
            **data,
            "kind": EventKind(data["kind"]),
            "provenance": EventProvenance(data["provenance"]),
            "trust": EventTrust(data["trust"]),
            "surface": AttackSurface(data["surface"]) if data["surface"] else None,
        }
    )


def write_event(journal: Path, event: AgentEvent) -> None:
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(asdict(event)) + "\n")
