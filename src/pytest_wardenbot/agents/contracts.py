"""Transport-independent contracts for bounded, instrumented agent trials.

Event trust describes the integrity of an observation, never the authority of
the delivered content. A harness can faithfully record an untrusted tool result.
Only separately supplied :class:`HarnessTrace` observations are authoritative;
an agent cannot promote its own events by setting provenance or trust fields.
Payload fields are deliberately absent from repr. Use the reporting helpers to
export results; dataclasses.asdict is an unsanitized internal representation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AgentCapability(StrEnum):
    ISOLATED_STATE = "isolated_state"
    TOOL_CALLS = "tool_calls"
    TOOL_RESULTS = "tool_results"
    TOOL_DESCRIPTIONS = "tool_descriptions"
    RESOURCES = "resources"
    PROMPTS = "prompts"
    TRACE = "trace"


class AttackSurface(StrEnum):
    TOOL_RESULT = "tool_result"
    TOOL_DESCRIPTION = "tool_description"
    RESOURCE = "resource"
    PROMPT = "prompt"


class Outcome(StrEnum):
    VIOLATED = "violated"
    RESISTED = "resisted"
    INCONCLUSIVE = "inconclusive"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class Exposure(StrEnum):
    NOT_OBSERVED = "not_observed"
    DELIVERED = "delivered"
    PROCESSED = "processed"


class EventKind(StrEnum):
    TOOL_DESCRIPTION = "tool_description"
    TOOL_RESULT = "tool_result"
    RESOURCE = "resource"
    PROMPT = "prompt"
    PROCESSED = "processed"
    TOOL_CALL = "tool_call"
    TOOL_EFFECT = "tool_effect"


class EventProvenance(StrEnum):
    HARNESS = "harness"
    TARGET = "target"
    ATTACK = "attack"


class EventTrust(StrEnum):
    OBSERVED = "observed"
    UNTRUSTED = "untrusted"


class ReasonCode(StrEnum):
    MISSING_CAPABILITY = "missing_capability"
    NO_HARNESS_TRACE = "no_harness_trace"
    MISSING_EXPOSURE = "missing_exposure"
    PROCESSING_NOT_OBSERVED = "processing_not_observed"
    INCOMPLETE_TRACE = "incomplete_trace"
    FORBIDDEN_TOOL_EFFECT = "forbidden_tool_effect"
    CANARY_LEAK = "canary_leak"
    BOUNDARY_HELD = "boundary_held"
    INVALID_TRACE = "invalid_trace"
    INVALID_TARGET_RESULT = "invalid_target_result"
    TURN_LIMIT_EXCEEDED = "turn_limit_exceeded"
    TURN_LIMIT_EXHAUSTED = "turn_limit_exhausted"
    TARGET_ERROR = "target_error"
    OBSERVER_ERROR = "observer_error"
    RESET_ERROR = "reset_error"
    CLEANUP_ERROR = "cleanup_error"
    TIMEOUT = "timeout"


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError("Identifiers must be 1-128 ASCII letters, digits, or ._:-")


def _json_copy(value: object, *, _depth: int = 0) -> object:
    """Snapshot supported payloads without invoking arbitrary object's repr."""
    if _depth > 32:
        raise ValueError("Event payload nesting exceeds the supported depth")
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list | tuple):
        return [_json_copy(item, _depth=_depth + 1) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _json_copy(item, _depth=_depth + 1) for key, item in value.items()}
    raise ValueError("Event payloads must contain finite JSON-compatible values")


@dataclass(frozen=True)
class RunLimits:
    timeout_seconds: float = 30
    max_turns: int = 10
    cleanup_timeout_seconds: float = 5

    def __post_init__(self) -> None:
        for value in (self.timeout_seconds, self.cleanup_timeout_seconds):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Timeouts must be finite positive numbers")
        if isinstance(self.max_turns, bool) or not isinstance(self.max_turns, int):
            raise ValueError("max_turns must be a positive integer")
        if self.max_turns <= 0:
            raise ValueError("max_turns must be a positive integer")


@dataclass(frozen=True)
class AgentEvent:
    trial_id: str = field(repr=False)
    kind: EventKind
    provenance: EventProvenance = EventProvenance.TARGET
    trust: EventTrust = EventTrust.UNTRUSTED
    name: str = field(default="", repr=False)
    data: dict[str, object] = field(default_factory=dict, repr=False)
    surface: AttackSurface | None = None
    scenario_id: str | None = field(default=None, repr=False)
    scenario_version: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _identifier(self.trial_id)
        if not isinstance(self.kind, EventKind):
            raise ValueError("Event kind must be an EventKind")
        if not isinstance(self.provenance, EventProvenance) or not isinstance(
            self.trust, EventTrust
        ):
            raise ValueError("Event provenance and trust must use the declared enums")
        if not isinstance(self.name, str) or not isinstance(self.data, dict):
            raise ValueError("Event name and data must be a string and dictionary")
        if self.surface is not None and not isinstance(self.surface, AttackSurface):
            raise ValueError("Event surface must be an AttackSurface")
        for label in (self.scenario_id, self.scenario_version):
            if label is not None:
                _identifier(label)
        object.__setattr__(self, "data", _json_copy(self.data))


@dataclass(frozen=True)
class Scenario:
    id: str = field(repr=False)
    version: str = field(repr=False)
    task: str = field(repr=False)
    surface: AttackSurface
    required_capabilities: frozenset[AgentCapability] = frozenset()
    forbidden_tool: str | None = field(default=None, repr=False)
    canary: str | None = field(default=None, repr=False)
    require_processing: bool = False

    def __post_init__(self) -> None:
        _identifier(self.id)
        _identifier(self.version)
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("Scenario requires a nonempty legitimate task")
        if not isinstance(self.surface, AttackSurface):
            raise ValueError("Scenario surface must be an AttackSurface")
        capabilities = frozenset(self.required_capabilities)
        if not all(isinstance(item, AgentCapability) for item in capabilities):
            raise ValueError("Scenario capabilities must use AgentCapability")
        object.__setattr__(self, "required_capabilities", capabilities)
        for value in (self.forbidden_tool, self.canary):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("Scenario assertions must be nonempty strings")
        if self.forbidden_tool is None and self.canary is None:
            raise ValueError("Scenario requires a forbidden tool or synthetic canary assertion")
        if not isinstance(self.require_processing, bool):
            raise ValueError("require_processing must be a boolean")


@dataclass(frozen=True)
class TargetRun:
    """Agent claims. Neither completion flags nor event labels establish trust.

    ``limit_exhausted`` means a required next step was prevented by the turn
    budget. Legitimately finishing on the final allowed turn does not set it.
    Budget-truncated execution cannot establish observed resistance.
    """

    events: tuple[AgentEvent, ...] = field(default=(), repr=False)
    task_succeeded: bool | None = None
    trace_complete: bool = False
    turns: int = 0
    final_text: str = field(default="", repr=False)
    usage: dict[str, int | float] | None = field(default=None, repr=False)
    limit_exhausted: bool = False


@dataclass(frozen=True)
class HarnessTrace:
    """Trusted fixture observations for one trial and its asserted local boundary.

    ``complete`` means the recording sink was active throughout this trial and
    covers the asserted effects. It does not claim coverage of external tools.
    PROCESSED events describe independent processing instrumentation, when such
    a hook exists. Mere delivery establishes no model consumption claim.
    """

    trial_id: str = field(repr=False)
    events: tuple[AgentEvent, ...] = field(default=(), repr=False)
    complete: bool = False


@dataclass(frozen=True)
class RunResult:
    trial_id: str = field(repr=False)
    scenario_id: str = field(repr=False)
    scenario_version: str = field(repr=False)
    outcome: Outcome
    exposure: Exposure = Exposure.NOT_OBSERVED
    task_succeeded: bool | None = None
    events: tuple[AgentEvent, ...] = field(default=(), repr=False)
    reason_codes: tuple[ReasonCode, ...] = ()
    limits: RunLimits = field(default_factory=RunLimits)
    turns: int = 0
    usage: dict[str, int | float] | None = field(default=None, repr=False)


@runtime_checkable
class AgentTarget(Protocol):
    """Application-owned agent integration; core imports no MCP/vendor types.

    ``reset`` must establish clean state for the supplied trial identifier and
    release it afterward. Concurrent implementations must isolate trial IDs.
    ``max_turns`` is a cooperative execution bound: integrations must enforce
    it in their own loop and report real turns. The runner enforces a deadline
    and rejects reported over-limit runs, but cannot preempt hidden tool calls.
    """

    name: str
    capabilities: frozenset[AgentCapability]

    async def run(self, task: str, *, trial_id: str, max_turns: int) -> TargetRun: ...

    async def reset(self, trial_id: str) -> None: ...
