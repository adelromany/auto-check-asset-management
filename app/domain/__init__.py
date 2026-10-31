"""The handover domain: pure Python, standard library only."""

from .handover_rules import (
    StageState,
    can_run,
    derive_status,
    missing_steps,
)
from .stages import (
    MANUAL_STAGES,
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
)

__all__ = [
    "MANUAL_STAGES",
    "STAGE_DEPENDENCIES",
    "STAGE_ORDER",
    "HandoverStatus",
    "Stage",
    "StageState",
    "StageStatus",
    "can_run",
    "derive_status",
    "missing_steps",
]
