"""The case domain: pure Python, standard library only."""

from .catalog import (
    MANUAL_OPERATIONS,
    RECOMMENDED_AFTER,
    CaseKind,
    Operation,
    operation_title,
    operations_for,
)
from .handover_rules import (
    StageState,
    advice,
    derive_status,
    gaps,
    missing_steps,
    next_operation,
)
from .stages import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
)

# ``MANUAL_STAGES`` is the old name of ``MANUAL_OPERATIONS``.
MANUAL_STAGES = MANUAL_OPERATIONS

__all__ = [
    "MANUAL_OPERATIONS",
    "MANUAL_STAGES",
    "RECOMMENDED_AFTER",
    "STAGE_DEPENDENCIES",
    "STAGE_ORDER",
    "CaseKind",
    "HandoverStatus",
    "Operation",
    "Stage",
    "StageState",
    "StageStatus",
    "advice",
    "derive_status",
    "gaps",
    "missing_steps",
    "next_operation",
    "operation_title",
    "operations_for",
]
