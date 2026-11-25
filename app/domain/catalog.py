"""Pure operation catalog: case kinds, operation keys, lanes and hints.

One place decides which operations a case of a given kind has, how they are
grouped on screen, and which order is *recommended* (never enforced). No I/O,
no framework, no clock (ARC-01).

BIZ-19 (owner instruction, 2026-11-15): every operation is independent. The
mapping below is advice only; a case can record any operation at any time.
"""

from __future__ import annotations

from enum import StrEnum


class CaseKind(StrEnum):
    """The two kinds of case this application manages."""

    HANDOVER = "handover"
    MAINTENANCE = "maintenance"


class Operation(StrEnum):
    """Every operation key, for both kinds. The key is stored in the database."""

    # Handover ------------------------------------------------------------
    DEVICE_STATUS = "device_status"
    RECIPIENT_ITEMS = "recipient_items"
    DEVICE_PREPARED = "device_prepared"
    USER_SIGNED_IN = "user_signed_in"
    AGENT_REPORT = "agent_report"
    SOFTWARE_CHECK = "software_check"
    RECIPIENT_CHECK = "recipient_check"
    CHECKOUT = "checkout"
    REPORT_PRINTED = "report_printed"
    USER_SIGNED = "user_signed"
    DOCUMENT_SCANNED = "document_scanned"
    DOCUMENT_PUSHED = "document_pushed"
    # Maintenance ---------------------------------------------------------
    RECEIVED = "received"
    DIAGNOSIS = "diagnosis"
    SNIPEIT_STATUS = "snipeit_status"
    TAKEN_BACK = "taken_back"
    SENT_OUT = "sent_out"
    RETURNED = "returned"
    READY_STATUS = "ready_status"


# Screen order (V2). DEVICE_PREPARED / USER_SIGNED_IN / USER_SIGNED stay in the
# enum only so old database rows still load.
HANDOVER_OPERATIONS: tuple[Operation, ...] = (
    Operation.DEVICE_STATUS,
    Operation.AGENT_REPORT,
    Operation.SOFTWARE_CHECK,
    Operation.REPORT_PRINTED,
    Operation.RECIPIENT_CHECK,
    Operation.RECIPIENT_ITEMS,
    Operation.CHECKOUT,
    Operation.DOCUMENT_SCANNED,
    Operation.DOCUMENT_PUSHED,
)

# Maintenance operations in screen order.
MAINTENANCE_OPERATIONS: tuple[Operation, ...] = (
    Operation.RECEIVED,
    Operation.DIAGNOSIS,
    Operation.SNIPEIT_STATUS,
    Operation.TAKEN_BACK,
    Operation.SENT_OUT,
    Operation.RETURNED,
    Operation.READY_STATUS,
)

OPERATIONS_BY_KIND: dict[CaseKind, tuple[Operation, ...]] = {
    CaseKind.HANDOVER: HANDOVER_OPERATIONS,
    CaseKind.MAINTENANCE: MAINTENANCE_OPERATIONS,
}

# Short titles: a tile never carries more than three words.
OPERATION_TITLES: dict[Operation, str] = {
    Operation.DEVICE_STATUS: "Device status",
    Operation.RECIPIENT_ITEMS: "Recipient items",
    # Legacy keys kept for old rows.
    Operation.DEVICE_PREPARED: "Device prepared",
    Operation.USER_SIGNED_IN: "User signed in",
    Operation.AGENT_REPORT: "Agent report",
    Operation.SOFTWARE_CHECK: "Software",
    Operation.RECIPIENT_CHECK: "Recipient",
    Operation.CHECKOUT: "Checkout",
    Operation.REPORT_PRINTED: "Print form",
    Operation.USER_SIGNED: "Signed paper",
    Operation.DOCUMENT_SCANNED: "Scan",
    Operation.DOCUMENT_PUSHED: "Push",
    Operation.RECEIVED: "Received",
    Operation.DIAGNOSIS: "Reason",
    Operation.SNIPEIT_STATUS: "Status Maintenance",
    Operation.TAKEN_BACK: "Taken back",
    Operation.SENT_OUT: "Sent",
    Operation.RETURNED: "Returned",
    Operation.READY_STATUS: "Status Ready",
}

# Visual grouping only. The order is a reading order, not a lock.
LANES: dict[CaseKind, tuple[tuple[str, tuple[Operation, ...]], ...]] = {
    CaseKind.HANDOVER: (
        (
            "Device",
            (
                Operation.DEVICE_STATUS,
                Operation.AGENT_REPORT,
                Operation.SOFTWARE_CHECK,
            ),
        ),
        ("Form", (Operation.REPORT_PRINTED,)),
        (
            "Recipient",
            (
                Operation.RECIPIENT_CHECK,
                Operation.RECIPIENT_ITEMS,
                Operation.CHECKOUT,
            ),
        ),
        (
            "Paper",
            (
                Operation.DOCUMENT_SCANNED,
                Operation.DOCUMENT_PUSHED,
            ),
        ),
    ),
    CaseKind.MAINTENANCE: (
        ("Intake", (Operation.RECEIVED, Operation.DIAGNOSIS)),
        ("Status", (Operation.SNIPEIT_STATUS, Operation.TAKEN_BACK, Operation.READY_STATUS)),
        ("Transit", (Operation.SENT_OUT, Operation.RETURNED)),
    ),
}

# Pure hints: "Usually done after X". Never blocks, never returns 409.
RECOMMENDED_AFTER: dict[Operation, tuple[Operation, ...]] = {
    Operation.DEVICE_STATUS: (),
    Operation.AGENT_REPORT: (Operation.DEVICE_STATUS,),
    Operation.SOFTWARE_CHECK: (Operation.AGENT_REPORT,),
    Operation.REPORT_PRINTED: (Operation.SOFTWARE_CHECK,),
    Operation.RECIPIENT_CHECK: (Operation.SOFTWARE_CHECK,),
    Operation.RECIPIENT_ITEMS: (Operation.RECIPIENT_CHECK,),
    Operation.CHECKOUT: (Operation.RECIPIENT_ITEMS,),
    Operation.DOCUMENT_SCANNED: (Operation.CHECKOUT,),
    Operation.DOCUMENT_PUSHED: (Operation.DOCUMENT_SCANNED,),
    Operation.RECEIVED: (),
    Operation.DIAGNOSIS: (Operation.RECEIVED,),
    Operation.SNIPEIT_STATUS: (Operation.RECEIVED,),
    Operation.TAKEN_BACK: (Operation.RECEIVED,),
    Operation.SENT_OUT: (Operation.DIAGNOSIS, Operation.SNIPEIT_STATUS),
    Operation.RETURNED: (Operation.SENT_OUT,),
    Operation.READY_STATUS: (Operation.RETURNED,),
}

# Operations an engineer confirms with one click (no evidence payload).
MANUAL_OPERATIONS: frozenset[Operation] = frozenset(
    {
        Operation.REPORT_PRINTED,
        Operation.RECEIVED,
        Operation.DIAGNOSIS,
        Operation.SNIPEIT_STATUS,
        Operation.TAKEN_BACK,
        Operation.SENT_OUT,
        Operation.RETURNED,
        Operation.READY_STATUS,
    }
)

# Preset chips offered next to the mandatory free-text reason.
NOT_DONE_PRESET_REASONS: tuple[str, ...] = (
    "Not applicable",
    "Device not available",
    "Will do later",
)
NOT_DONE_REASON_MIN = 3
NOT_DONE_REASON_MAX = 300


def operation_title(operation: Operation) -> str:
    return OPERATION_TITLES.get(operation, operation.value)


def operations_for(kind: CaseKind | str) -> tuple[Operation, ...]:
    resolved = CaseKind(str(kind))
    return OPERATIONS_BY_KIND[resolved]


def lanes_for(kind: CaseKind | str) -> tuple[tuple[str, tuple[Operation, ...]], ...]:
    resolved = CaseKind(str(kind))
    return LANES[resolved]


def operation_from_key(key: str) -> Operation:
    """Parse an operation key, raising ``ValueError`` when unknown."""
    try:
        return Operation(key)
    except ValueError as exc:
        raise ValueError(f"Unknown operation: {key}") from exc
