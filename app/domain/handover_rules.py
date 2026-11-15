"""Pure case rules: derived status, missing operations, advice, next action.

No I/O, no clock reads, no framework imports (ARC-01). Everything is decided
from the operation states passed in.

BIZ-19 (owner instruction, 2026-11-15): operations are independent. The old
dependency table is now ``RECOMMENDED_AFTER`` and only produces a warning.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from .catalog import RECOMMENDED_AFTER, Operation, operation_title
from .stages import (
    SATISFIED_STATUSES,
    HandoverStatus,
    StageStatus,
)
from .timeutil import as_utc


@dataclass(frozen=True)
class StageState:
    """The parts of one operation the rules care about."""

    stage: Operation
    status: StageStatus = StageStatus.PENDING
    reason: str | None = None


_STAGE_HINTS: dict[Operation, str] = {
    Operation.DEVICE_PREPARED: "Confirm the device is prepared.",
    Operation.USER_SIGNED_IN: "Confirm the user signed in on the device.",
    Operation.AGENT_REPORT: "Run the agent on the device; its serial must match.",
    Operation.SOFTWARE_CHECK: "Verify required software and Windows activation.",
    Operation.RECIPIENT_CHECK: "Search Snipe-IT for the recipient and confirm.",
    Operation.CHECKOUT: "Checkout the device to the confirmed recipient.",
    Operation.REPORT_PRINTED: "Print the agent report.",
    Operation.USER_SIGNED: "Get the printed sheet signed on paper.",
    Operation.DOCUMENT_SCANNED: "Upload the scanned signed sheet.",
    Operation.DOCUMENT_PUSHED: "Push the scan to the device's Snipe-IT asset.",
    Operation.RECEIVED: "Record the reported issue and received condition.",
    Operation.DIAGNOSIS: "Record the diagnosis category and finding.",
    Operation.SNIPEIT_STATUS: "Set the Snipe-IT status to the maintenance label.",
    Operation.SENT_OUT: "Record where the device was sent and when.",
    Operation.RETURNED: "Record the return date and the outcome.",
}


def _by_stage(stages: Sequence[StageState]) -> dict[Operation, StageState]:
    return {state.stage: state for state in stages}


def _state_for(states: dict[Operation, StageState], stage: Operation) -> StageState:
    return states.get(stage) or StageState(stage)


def derive_status(
    stages: Sequence[StageState],
    *,
    operations: Sequence[Operation] | None = None,
    cancelled: bool = False,
    closed_with_gaps: bool = False,
    updated_at: datetime | None = None,
    now: datetime | None = None,
    stall_hours: int = 0,
) -> HandoverStatus:
    """Derive the case status from its operation states (BIZ-14, BIZ-20).

    ``cancelled`` and ``closed_with_gaps`` are explicit and always win; they
    are never derived over. A failed operation no longer stalls a case; the
    only ``stalled`` rule left is age (no activity for ``STALL_HOURS``).
    """
    if cancelled:
        return HandoverStatus.CANCELLED
    if closed_with_gaps:
        return HandoverStatus.CLOSED_WITH_GAPS

    order = tuple(operations) if operations is not None else tuple(
        state.stage for state in stages
    )
    states = _by_stage(stages)
    statuses = [_state_for(states, stage).status for stage in order]

    if statuses and all(status in SATISFIED_STATUSES for status in statuses):
        return HandoverStatus.COMPLETED
    if stalled_by_age(updated_at, now, stall_hours):
        return HandoverStatus.STALLED
    if not statuses or all(status is StageStatus.PENDING for status in statuses):
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


def needs_attention(stages: Sequence[StageState]) -> bool:
    """True when at least one operation is attempted and failed."""
    return any(state.status is StageStatus.FAILED for state in stages)


def missing_steps(stages: Sequence[StageState]) -> list[dict[str, str | None]]:
    """Every operation that is not passed, with reason and an actionable hint."""
    missing: list[dict[str, str | None]] = []
    for state in stages:
        if state.status in SATISFIED_STATUSES:
            continue
        missing.append(
            {
                "stage": state.stage.value,
                "status": state.status.value,
                "reason": state.reason,
                "hint": _hint_for(state),
            }
        )
    return missing


def gaps(stages: Sequence[StageState]) -> list[dict[str, str | None]]:
    """The not-passed operations in closing form: operation, status, reason."""
    return [
        {
            "operation": state.stage.value,
            "status": state.status.value,
            "reason": state.reason,
        }
        for state in stages
        if state.status not in SATISFIED_STATUSES
    ]


def advice(operation: Operation, stages: Sequence[StageState]) -> list[str]:
    """Non-blocking ordering hints, e.g. "Usually done after Recipient".

    Only predecessors that are part of this case and not passed produce a
    hint. The caller records them in the outcome detail and shows them; they
    never stop the operation.
    """
    states = _by_stage(stages)
    warnings: list[str] = []
    for predecessor in RECOMMENDED_AFTER.get(operation, ()):
        if predecessor not in states:
            continue
        if states[predecessor].status in SATISFIED_STATUSES:
            continue
        warnings.append(f"Usually done after {operation_title(predecessor)}")
    return warnings


def performed_before(
    operation: Operation, stages: Sequence[StageState]
) -> list[str]:
    """The recommended predecessors that are still not passed (audit detail)."""
    states = _by_stage(stages)
    return [
        predecessor.value
        for predecessor in RECOMMENDED_AFTER.get(operation, ())
        if predecessor in states
        and states[predecessor].status not in SATISFIED_STATUSES
    ]


def next_operation(
    stages: Sequence[StageState], operations: Sequence[Operation]
) -> Operation | None:
    """The first unfinished operation in reading order; a suggestion only."""
    states = _by_stage(stages)
    for operation in operations:
        if _state_for(states, operation).status not in SATISFIED_STATUSES:
            return operation
    return None


def _hint_for(state: StageState) -> str:
    base = _STAGE_HINTS.get(state.stage, "Complete this operation.")
    if state.status is StageStatus.FAILED and state.reason:
        return f"{state.reason} — {base}"
    if state.status is StageStatus.NOT_DONE:
        return (
            f"Not done: {state.reason}"
            if state.reason
            else "Not done: no reason recorded."
        )
    return base
