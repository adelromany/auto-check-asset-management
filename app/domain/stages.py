"""Operation keys, statuses and derived case statuses.

This module is the single source of truth for operation keys (CLN-05/CLN-06).
The catalog itself lives in :mod:`app.domain.catalog`; the names here stay for
backward-compatible imports (``Stage`` is the old name of an operation).
"""

from __future__ import annotations

from enum import StrEnum

from .catalog import (  # re-exported for callers that used this module only
    HANDOVER_OPERATIONS,
    MAINTENANCE_OPERATIONS,
    MANUAL_OPERATIONS,
    NOT_DONE_PRESET_REASONS,
    OPERATION_TITLES,
    OPERATIONS_BY_KIND,
    RECOMMENDED_AFTER,
    CaseKind,
    Operation,
    operation_from_key,
    operation_title,
    operations_for,
    lanes_for,
)

# The old name of "operation"; kept so existing imports keep working.
Stage = Operation

STAGE_ORDER: tuple[Operation, ...] = HANDOVER_OPERATIONS

# DEPRECATED alias. Ordering is advice only (BIZ-19); code must call
# ``advice()`` in handover_rules instead of treating this as a gate.
STAGE_DEPENDENCIES: dict[Operation, tuple[Operation, ...]] = RECOMMENDED_AFTER


class StageStatus(StrEnum):
    """The four outcome states one operation can have.

    ``passed`` is the only state that counts as done. ``not_done`` is an
    explicit engineer decision with a reason; ``failed`` was attempted and can
    be retried. Neither blocks any other operation.
    """

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NOT_DONE = "not_done"


# Clearer name for new code; same enum.
OperationStatus = StageStatus


class HandoverStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    STALLED = "stalled"
    COMPLETED = "completed"
    CLOSED_WITH_GAPS = "closed_with_gaps"
    CANCELLED = "cancelled"


INACTIVE_CASE_STATUSES: tuple[str, ...] = (
    HandoverStatus.COMPLETED.value,
    HandoverStatus.CLOSED_WITH_GAPS.value,
    HandoverStatus.CANCELLED.value,
)

SATISFIED_STATUSES: frozenset[StageStatus] = frozenset({StageStatus.PASSED})


def stage_from_key(key: str) -> Operation:
    """Parse an API/database operation key, raising ``ValueError`` if unknown."""
    try:
        return operation_from_key(key)
    except ValueError as exc:
        raise ValueError(f"Unknown stage: {key}") from exc
