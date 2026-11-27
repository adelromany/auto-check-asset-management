"""Tests for the single handover case outcome."""

from __future__ import annotations

import pytest

from app.domain.catalog import HANDOVER_OPERATIONS
from app.domain.handover_rules import (
    Outcome,
    StageState,
    case_outcome,
    case_warnings,
    kind_label,
    missing_parts,
    required_operations,
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
    assert missing_parts(states, "none") == []


@pytest.mark.parametrize(
    ("mode", "label", "required_count"),
    [("none", "Lab only", 3), ("snipeit", "Lab + user", 9), ("pending_user", "User not ready", 9)],
)
def test_handover_type_requirements(mode: str, label: str, required_count: int) -> None:
    assert kind_label(mode) == label
    assert len(required_operations(mode)) == required_count


def test_lab_user_with_one_missing_is_not_complete() -> None:
    states = [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS]
    states[-1] = StageState(HANDOVER_OPERATIONS[-1], StageStatus.PENDING)
    assert case_outcome(states, recipient_mode="snipeit") is Outcome.NOT_COMPLETE
    assert missing_parts(states, "snipeit")


def test_pending_user_waits_for_recipient_parts_then_completes() -> None:
    states = _states(
        device_status=StageStatus.PASSED,
        agent_report=StageStatus.PASSED,
        software_check=StageStatus.PASSED,
        report_printed=StageStatus.PASSED,
        document_scanned=StageStatus.PASSED,
        document_pushed=StageStatus.PASSED,
    )
    assert case_outcome(states, recipient_mode="pending_user") is Outcome.NOT_COMPLETE
    states = [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS]
    assert case_outcome(states, recipient_mode="pending_user") is Outcome.COMPLETE
    assert case_outcome(states, recipient_mode="not_in_snipeit") is Outcome.COMPLETE


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
    assert "Software" in missing_parts(states, "none")
