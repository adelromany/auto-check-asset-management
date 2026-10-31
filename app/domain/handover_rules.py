"""Pure handover rules: derived status, missing steps, runnability.

No I/O, no clock reads, no framework imports (ARC-01). Everything is decided
from the stage states passed in.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .stages import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
)


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
    Stage.RECIPIENT_CHECK: "Search Snipe-IT for the recipient and confirm the match.",
    Stage.CHECKOUT: "Checkout the device to the confirmed recipient in Snipe-IT.",
    Stage.REPORT_PRINTED: "Print the agent report page.",
    Stage.USER_SIGNED: "Get the printed sheet signed on paper.",
    Stage.DOCUMENT_SCANNED: "Upload the scanned signed sheet.",
    Stage.DOCUMENT_PUSHED: "Push the scan to the device's Snipe-IT asset.",
}


def _by_stage(stages: Sequence[StageState]) -> dict[Stage, StageState]:
    return {state.stage: state for state in stages}


def _state_for(states: dict[Stage, StageState], stage: Stage) -> StageState:
    return states.get(stage) or StageState(stage)


def derive_status(
    stages: Sequence[StageState], *, cancelled: bool = False
) -> HandoverStatus:
    """Derive the handover status from its stage states (BIZ-14).

    ``cancelled`` is explicit and always wins; it is never derived over.
    """
    if cancelled:
        return HandoverStatus.CANCELLED

    states = _by_stage(stages)
    statuses = [_state_for(states, stage).status for stage in STAGE_ORDER]

    if all(status is StageStatus.PASSED for status in statuses):
        return HandoverStatus.COMPLETED
    if any(
        status in (StageStatus.FAILED, StageStatus.BLOCKED) for status in statuses
    ):
        return HandoverStatus.STALLED
    if all(status is StageStatus.PENDING for status in statuses):
        return HandoverStatus.DRAFT
    return HandoverStatus.IN_PROGRESS


def missing_steps(stages: Sequence[StageState]) -> list[dict[str, str | None]]:
    """Every stage that is not passed, with its stored reason and a hint."""
    states = _by_stage(stages)
    missing: list[dict[str, str | None]] = []
    for stage in STAGE_ORDER:
        state = _state_for(states, stage)
        if state.status is StageStatus.PASSED:
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
    """A stage may run only when every dependency is ``passed`` (BIZ-05)."""
    states = _by_stage(stages)
    current = _state_for(states, stage)
    if current.status is StageStatus.PASSED:
        return False, "Stage already passed."

    for dependency in STAGE_DEPENDENCIES[stage]:
        dependency_state = _state_for(states, dependency)
        if dependency_state.status is not StageStatus.PASSED:
            return False, (
                f"Waiting for {dependency.value} "
                f"(currently {dependency_state.status.value})."
            )
    return True, ""
