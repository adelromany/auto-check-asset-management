"""The nine fixed handover stages: keys, order, dependencies and statuses.

This module is the single source of truth for stage keys (CLN-05/CLN-06).
"""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """One verifiable step of a handover, in the order it happens."""

    DEVICE_PREPARED = "device_prepared"
    USER_SIGNED_IN = "user_signed_in"
    AGENT_REPORT = "agent_report"
    RECIPIENT_CHECK = "recipient_check"
    CHECKOUT = "checkout"
    REPORT_PRINTED = "report_printed"
    USER_SIGNED = "user_signed"
    DOCUMENT_SCANNED = "document_scanned"
    DOCUMENT_PUSHED = "document_pushed"


STAGE_ORDER: tuple[Stage, ...] = (
    Stage.DEVICE_PREPARED,
    Stage.USER_SIGNED_IN,
    Stage.AGENT_REPORT,
    Stage.RECIPIENT_CHECK,
    Stage.CHECKOUT,
    Stage.REPORT_PRINTED,
    Stage.USER_SIGNED,
    Stage.DOCUMENT_SCANNED,
    Stage.DOCUMENT_PUSHED,
)

# BIZ: dependencies are fixed and one-directional (a DAG, no cycles).
STAGE_DEPENDENCIES: dict[Stage, tuple[Stage, ...]] = {
    Stage.DEVICE_PREPARED: (),
    Stage.USER_SIGNED_IN: (Stage.DEVICE_PREPARED,),
    Stage.AGENT_REPORT: (Stage.DEVICE_PREPARED,),
    Stage.RECIPIENT_CHECK: (Stage.AGENT_REPORT,),
    Stage.CHECKOUT: (Stage.RECIPIENT_CHECK,),
    Stage.REPORT_PRINTED: (Stage.AGENT_REPORT,),
    Stage.USER_SIGNED: (Stage.REPORT_PRINTED,),
    Stage.DOCUMENT_SCANNED: (Stage.USER_SIGNED,),
    Stage.DOCUMENT_PUSHED: (Stage.DOCUMENT_SCANNED,),
}

# Stages an engineer confirms by hand; the others are driven by the agent or
# by verified Snipe-IT calls.
MANUAL_STAGES: frozenset[Stage] = frozenset(
    {
        Stage.DEVICE_PREPARED,
        Stage.USER_SIGNED_IN,
        Stage.REPORT_PRINTED,
        Stage.USER_SIGNED,
    }
)


class StageStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"  # reserved; not used in v1


class HandoverStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    STALLED = "stalled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def stage_from_key(key: str) -> Stage:
    """Parse an API/database stage key, raising ``ValueError`` when unknown."""
    try:
        return Stage(key)
    except ValueError as exc:
        raise ValueError(f"Unknown stage: {key}") from exc
