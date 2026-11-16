"""Pure maintenance rules: state names, due dates, turnaround, and overdue policy (Part D)."""

from __future__ import annotations

from datetime import date

from app.domain.maintenance_rules import (
    MAINTENANCE_OVERDUE_DAYS,
    MaintenanceState,
    derive_maintenance_state,
    due_date,
    is_overdue,
    maintenance_label,
    turnaround_days,
)


def test_state_is_derived_only_from_the_transit_operations() -> None:
    assert derive_maintenance_state({}) is MaintenanceState.NEEDS_MAINTENANCE
    assert (
        derive_maintenance_state({"received": "passed"})
        is MaintenanceState.NEEDS_MAINTENANCE
    )
    assert (
        derive_maintenance_state({"sent_out": "passed"})
        is MaintenanceState.IN_MAINTENANCE
    )
    assert (
        derive_maintenance_state({"sent_out": "passed", "returned": "passed"})
        is MaintenanceState.RETURNED
    )
    # not_done/failed never pretend the device moved.
    assert (
        derive_maintenance_state({"sent_out": "failed"})
        is MaintenanceState.NEEDS_MAINTENANCE
    )
    assert (
        derive_maintenance_state({"sent_out": "not_done"})
        is MaintenanceState.NEEDS_MAINTENANCE
    )


def test_due_date_uses_expected_return_or_fourteen_days_after_sending() -> None:
    sent = date(2026, 11, 1)
    expected = date(2026, 11, 10)

    assert due_date(sent_date=sent, expected_return_date=expected) == expected
    assert due_date(sent_date=sent, expected_return_date=None) == date(2026, 11, 15)
    assert MAINTENANCE_OVERDUE_DAYS == 14


def test_overdue_only_when_open_and_past_the_due_date() -> None:
    sent = date(2026, 11, 1)

    assert is_overdue(
        sent_date=sent,
        expected_return_date=None,
        today=date(2026, 11, 16),
        returned=False,
    )
    assert not is_overdue(
        sent_date=sent,
        expected_return_date=None,
        today=date(2026, 11, 15),
        returned=False,
    )
    assert not is_overdue(
        sent_date=sent,
        expected_return_date=None,
        today=date(2026, 12, 1),
        returned=True,
    )
    assert not is_overdue(
        sent_date=None,
        expected_return_date=None,
        today=date(2026, 12, 1),
        returned=False,
    )


def test_turnaround_days_calculation() -> None:
    sent = date(2026, 11, 1)
    returned = date(2026, 11, 8)
    assert turnaround_days(sent_date=sent, returned_date=returned) == 7
    assert turnaround_days(sent_date=sent, returned_date=None) is None
    assert turnaround_days(sent_date=None, returned_date=returned) is None
    assert turnaround_days(sent_date=returned, returned_date=sent) is None


def test_maintenance_labels() -> None:
    assert maintenance_label(MaintenanceState.NEEDS_MAINTENANCE) == "Needs maintenance"
    assert maintenance_label(MaintenanceState.IN_MAINTENANCE) == "In maintenance"
    assert (
        maintenance_label(MaintenanceState.RETURNED) == "Returned from maintenance"
        or maintenance_label(MaintenanceState.RETURNED) == "Returned"
    )
