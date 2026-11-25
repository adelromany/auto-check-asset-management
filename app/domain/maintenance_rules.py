"""Pure maintenance rules: state, due date, turnaround, and overdue policy (ARC-01).

No I/O, no framework imports, no clock.
States: Needs maintenance, In maintenance, Returned from maintenance.
Transit operations: received, sent_out, returned.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from enum import StrEnum

# Default turnaround target (Q-20).
MAINTENANCE_OVERDUE_DAYS = 14


class MaintenanceState(StrEnum):
    """The three V2 states of a maintenance case."""

    WITH_IT = "with_it"
    AT_VENDOR = "at_vendor"
    RETURNED = "returned"

    # Legacy names retained as aliases for callers compiled against Phase 01.
    NEEDS_MAINTENANCE = "with_it"
    IN_MAINTENANCE = "at_vendor"


_LABELS: dict[MaintenanceState, str] = {
    MaintenanceState.WITH_IT: "Needs maintenance",
    MaintenanceState.AT_VENDOR: "In maintenance",
    MaintenanceState.RETURNED: "Returned from maintenance",
}


def maintenance_label(state: MaintenanceState | str) -> str:
    try:
        resolved = MaintenanceState(state)
        return _LABELS[resolved]
    except (ValueError, KeyError):
        return str(state).replace("_", " ").title()


def derive_maintenance_state(
    statuses: Mapping[str, str],
) -> MaintenanceState:
    """Returned wins over sent out; anything else still needs maintenance.

    Only ``passed`` moves the device. A failed or not-done transit operation
    leaves the case where it was, never in a state the device is not in.
    """
    if statuses.get("returned") == "passed":
        return MaintenanceState.RETURNED
    if statuses.get("sent_out") == "passed":
        return MaintenanceState.AT_VENDOR
    return MaintenanceState.WITH_IT


def days_in_maintenance(
    received_date: date | None,
    returned_date: date | None,
    today: date,
) -> int:
    """Return calendar days spent in maintenance, never less than zero."""
    start = received_date
    if start is None:
        return 0
    end = returned_date or today
    return max(0, (end - start).days)


def turnaround_days(
    *,
    sent_date: date | None,
    returned_date: date | None,
) -> int | None:
    """Calculate elapsed turnaround days between sent_date and returned_date."""
    if sent_date is None or returned_date is None:
        return None
    delta = (returned_date - sent_date).days
    if delta < 0:
        return None
    return delta


def due_date(
    *,
    sent_date: date | None,
    expected_return_date: date | None,
) -> date | None:
    """The owner's expected return date, or the 14-day fallback after sending."""
    if expected_return_date is not None:
        return expected_return_date
    if sent_date is None:
        return None
    return sent_date + timedelta(days=MAINTENANCE_OVERDUE_DAYS)


def is_overdue(
    *,
    sent_date: date | None,
    expected_return_date: date | None,
    today: date,
    returned: bool,
) -> bool:
    """A warning indicator; it never changes an operation or case status."""
    if returned:
        return False
    due = due_date(sent_date=sent_date, expected_return_date=expected_return_date)
    return due is not None and today > due
