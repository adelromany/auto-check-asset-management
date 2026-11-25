"""Tests for the single handover case outcome."""

from __future__ import annotations

import pytest

from app.domain.catalog import HANDOVER_OPERATIONS
from app.domain.handover_rules import (
    Outcome,
    StageState,
    case_outcome,
    case_warnings,
    missing_parts,
)
from app.domain.stages import StageStatus


def _states(**statuses: StageStatus) -> list[StageState]:
    return [
        StageState(operation, statuses.get(operation.value, StageStatus.PENDING))
        for operation in HANDOVER_OPERATIONS
    ]


def test_cancelled_outcome_wins() -> None:
    assert (
        case_outcome(_states(), recipient_mode="none", cancelled=True)
        is Outcome.CANCELLED
    )


def test_all_operations_passed_is_complete() -> None:
    states = [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS]

    assert case_outcome(states, recipient_mode="snipeit") is Outcome.COMPLETE
    assert missing_parts(states) == []


def test_none_recipient_with_device_checks_is_ready() -> None:
    states = _states(
        device_status=StageStatus.PASSED,
        agent_report=StageStatus.PASSED,
        software_check=StageStatus.PASSED,
    )

    assert case_outcome(states, recipient_mode="none") is Outcome.READY
    assert "Recipient" in missing_parts(states)


@pytest.mark.parametrize(
    ("device_company", "recipient_company", "expected_codes"),
    [
        ("B.tech", "B.tech", []),
        ("B.tech", "btech", []),
        ("B.tech", "Mylo", ["company_mismatch"]),
        ("Mylo", "B.tech", ["company_mismatch"]),
        (None, "Mylo", []),
        ("B.tech", None, []),
    ],
)
def test_case_warnings_table(
    device_company: str | None,
    recipient_company: str | None,
    expected_codes: list[str],
) -> None:
    warnings = case_warnings(device_company, recipient_company)

    assert [warning.code for warning in warnings] == expected_codes
    assert all(warning.text for warning in warnings)


def test_case_warnings_company_unknown_is_kept() -> None:
    warnings = case_warnings("B.tech", None, company_unknown=True)

    assert [warning.code for warning in warnings] == ["company_unknown"]


def test_warning_never_changes_outcome() -> None:
    states = [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS]

    assert case_warnings("B.tech", "Mylo")[0].code == "company_mismatch"
    assert case_outcome(states, recipient_mode="snipeit") is Outcome.COMPLETE


def test_failed_operation_keeps_case_not_complete() -> None:
    states = _states(
        device_status=StageStatus.PASSED,
        agent_report=StageStatus.PASSED,
        software_check=StageStatus.FAILED,
    )

    assert case_outcome(states, recipient_mode="none") is Outcome.NOT_COMPLETE
    assert "Software" in missing_parts(states)
