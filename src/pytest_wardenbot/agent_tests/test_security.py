"""Instrumented, paired benign and attack regression cases."""

from __future__ import annotations

import pytest

from pytest_wardenbot._agent_plugin import assert_case
from pytest_wardenbot.agents.contracts import RunResult


@pytest.mark.wardenbot
@pytest.mark.severity_high
@pytest.mark.wardenbot_agent
def test_agent_security(
    request: pytest.FixtureRequest,
    wardenbot_agent_scenario,
    wardenbot_agent_attack_enabled: bool,
    wardenbot_agent_result: RunResult,
) -> None:
    """Verify baseline utility or the exposed, instrumented security boundary."""
    assert_case(
        request.node,
        wardenbot_agent_result,
        attack_enabled=wardenbot_agent_attack_enabled,
        required=bool(request.config.getoption("wardenbot_agent_required", default=False)),
    )
