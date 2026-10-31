"""Pure handover rules: derived status, missing steps, runnability.

No I/O, no clock reads, no framework imports (ARC-01). Everything is decided
from the stage states passed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .stages import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
)
from .timeutil import as_utc


@dataclass(frozen=True)
class StageState:
    """The parts of a stage the rules care about."""

    stage: Stage
    status: StageStatus = StageStatus.PENDING
    reason: str | None = None


_STAGE_HINTS: dict[Stage, str] = {
    Stage.DEVICE_PREPARED: "Confirm the device is prepared for handover.",
    Stage.USER_SIGNED_IN: "Confirm the user signed in on the device.",
    Stage.AGENT_REPORT: "Run the agent on the device; its serial must match.",
    Stage.SOFTWARE_CHECK: "Verify required software and Windows activation.",
    Stage.RECIPIENT_CHECK: "Search Snipe-IT for the recipient and confirm the match.",
    Stage.CHECKOUT: "Checkout the device to the confirmed recipient in Snipe-IT.",
    Stage.REPORT_PRINTED: "Print the agent report page.",
    Stage.USER_SIGNED: "Get the printed sheet signed on paper.",
    Stage.DOCUMENT_SCANNED: "Upload the scanned signed sheet.",
    Stage.DOCUMENT_PUSHED: "Push the scan to the device's Snipe-IT asset.",
}

# A skipped stage is a satisfied stage: the engineer decided it does not
# apply, so it completes the handover and satisfies dependencies exactly
# like ``passed`` — but it is never stalled-on and executable stages that
# depend on it may run.
SATISFIED_STATUSES: frozenset[StageStatus] = frozenset(
    {StageStatus.PASSED, StageStatus.SKIPPED}
)


def _by_stage(stages: Sequence[StageState]) -> dict[Stage, StageState]:
    return {state.stage: state for state in stages}


def _state_for(states: dict[Stage, StageState], stage: Stage) -> StageState:
    return states.get(stage) or StageState(stage)


def derive_status(
    stages: Sequence[StageState],
    *,
    cancelled: bool = False,
    updated_at: datetime | None = None,
    now: datetime | None = None,
    stall_hours: int = 0,
) -> HandoverStatus:
    """Derive the handover status from its stage states (BIZ-14).

    ``cancelled`` is explicit and always wins; it is never derived over.
    """
    if cancelled:
        return HandoverStatus.CANCELLED

    states = _by_stage(stages)
    statuses = [_state_for(states, stage).status for stage in STAGE_ORDER]
    terminal = [status in SATISFIED_STATUSES for status in statuses]

    if all(terminal):
        return HandoverStatus.COMPLETED
    if any(
        status in (StageStatus.FAILED, StageStatus.BLOCKED) for status in statuses
    ):
        return HandoverStatus.STALLED
    if stalled_by_age(updated_at, now, stall_hours):
        return HandoverStatus.STALLED
    if all(status is StageStatus.PENDING for status in statuses):
        return HandoverStatus.DRAFT
    return HandoverStatus.IN_PROGRESS


def stalled_by_age(
    updated_at: datetime | None, now: datetime | None, stall_hours: int
) -> bool:
    last_update = as_utc(updated_at)
    current = as_utc(now)
    if stall_hours <= 0 or last_update is None or current is None:
        return False
    return last_update < current - timedelta(hours=stall_hours)


def missing_steps(stages: Sequence[StageState]) -> list[dict[str, str | None]]:
    """Every stage that is not passed (or skipped), with reason and a hint.

    A skipped stage is a deliberate, satisfied decision, so it is never a
    missing step.
    """
    states = _by_stage(stages)
    missing: list[dict[str, str | None]] = []
    for stage in STAGE_ORDER:
        state = _state_for(states, stage)
        if state.status in SATISFIED_STATUSES:
            continue
        missing.append(
            {
                "stage": stage.value,
                "status": state.status.value,
                "reason": state.reason,
                "hint": _hint_for(state),
            }
        )
    return missing


def _hint_for(state: StageState) -> str:
    base = _STAGE_HINTS[state.stage]
    if state.status is StageStatus.BLOCKED:
        return f"{state.reason} — {base}" if state.reason else base
    if state.status is StageStatus.FAILED and state.reason:
        return f"{state.reason} — {base}"
    return base


def can_run(stage: Stage, stages: Sequence[StageState]) -> tuple[bool, str]:
    """A stage may run only when every dependency is ``passed`` or ``skipped``
    (BIZ-05; a skipped dependency is a satisfied dependency)."""
    states = _by_stage(stages)
    current = _state_for(states, stage)
    if current.status is StageStatus.PASSED:
        return False, "Stage already passed."
    if current.status is StageStatus.SKIPPED:
        return False, "Stage was skipped."

    for dependency in STAGE_DEPENDENCIES[stage]:
        dependency_state = _state_for(states, dependency)
        if dependency_state.status not in SATISFIED_STATUSES:
            return False, (
                f"Waiting for {dependency.value} "
                f"(currently {dependency_state.status.value})."
            )
    return True, ""
