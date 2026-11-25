"""Table-driven tests for the pure case domain (TST-03)."""

import pytest

from app.domain.catalog import (
    HANDOVER_OPERATIONS,
    MAINTENANCE_OPERATIONS,
    RECOMMENDED_AFTER,
    Operation,
)
from app.domain.company_rules import (
    company_conflict,
    company_known,
    normalize_company,
)
from app.domain.handover_rules import (
    StageState,
    advice,
    derive_status,
    gaps,
    missing_steps,
    next_operation,
    performed_before,
)
from app.domain.redaction import redact_agent_payload
from app.domain.stages import (
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
    stage_from_key,
)


def _stages(**statuses: StageStatus) -> list[StageState]:
    """Build one state per handover operation, defaulting to pending."""
    return [
        StageState(operation, statuses.get(operation.value, StageStatus.PENDING))
        for operation in HANDOVER_OPERATIONS
    ]


def test_stage_order_is_the_nine_handover_operations() -> None:
    assert [operation.value for operation in STAGE_ORDER] == [
        "device_status",
        "agent_report",
        "software_check",
        "report_printed",
        "recipient_check",
        "recipient_items",
        "checkout",
        "document_scanned",
        "document_pushed",
    ]


def test_maintenance_catalog_has_the_seven_phase_06_operations() -> None:
    assert [operation.value for operation in MAINTENANCE_OPERATIONS] == [
        "received",
        "diagnosis",
        "snipeit_status",
        "taken_back",
        "sent_out",
        "returned",
        "ready_status",
    ]


def test_recommended_order_is_known_operations_and_acyclic() -> None:
    for operation, predecessors in RECOMMENDED_AFTER.items():
        assert operation in Operation
        for predecessor in predecessors:
            assert predecessor in HANDOVER_OPERATIONS + MAINTENANCE_OPERATIONS
            if operation in HANDOVER_OPERATIONS:
                assert HANDOVER_OPERATIONS.index(predecessor) < HANDOVER_OPERATIONS.index(
                    operation
                )


@pytest.mark.parametrize(
    "stages,cancelled,closed_with_gaps,expected",
    [
        (_stages(), False, False, HandoverStatus.DRAFT),
        ([], False, False, HandoverStatus.DRAFT),
        (
            [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS],
            False,
            False,
            HandoverStatus.COMPLETED,
        ),
        (
            _stages(device_status=StageStatus.PASSED),
            False,
            False,
            HandoverStatus.IN_PROGRESS,
        ),
        # A failure no longer stalls the case; it needs attention instead.
        (
            _stages(agent_report=StageStatus.FAILED),
            False,
            False,
            HandoverStatus.IN_PROGRESS,
        ),
        (
            _stages(recipient_check=StageStatus.NOT_DONE),
            False,
            False,
            HandoverStatus.IN_PROGRESS,
        ),
        (
            _stages(device_status=StageStatus.FAILED),
            True,
            False,
            HandoverStatus.CANCELLED,
        ),
        (
            _stages(device_status=StageStatus.PASSED),
            False,
            True,
            HandoverStatus.CLOSED_WITH_GAPS,
        ),
    ],
)
def test_derive_status(
    stages: list[StageState],
    cancelled: bool,
    closed_with_gaps: bool,
    expected: HandoverStatus,
) -> None:
    assert (
        derive_status(
            stages, cancelled=cancelled, closed_with_gaps=closed_with_gaps
        )
        is expected
    )


def test_age_is_the_only_stall_rule() -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    old = now - timedelta(hours=30)
    stages = _stages(device_status=StageStatus.FAILED)
    assert (
        derive_status(stages, updated_at=old, now=now, stall_hours=24)
        is HandoverStatus.STALLED
    )
    assert (
        derive_status(stages, updated_at=now, now=now, stall_hours=24)
        is HandoverStatus.IN_PROGRESS
    )
    assert (
        derive_status(stages, updated_at=old, now=now, stall_hours=0)
        is HandoverStatus.IN_PROGRESS
    )


def test_advice_warns_without_blocking() -> None:
    stages = _stages()
    assert "Usually done after Recipient items" in advice(
        Operation.CHECKOUT, stages
    )
    assert "Usually done after Agent report" in advice(
        Operation.SOFTWARE_CHECK, stages
    )


def test_advice_is_empty_when_the_predecessor_passed() -> None:
    stages = _stages(
        recipient_items=StageStatus.PASSED,
        software_check=StageStatus.PASSED,
    )
    assert advice(Operation.CHECKOUT, stages) == []
    assert performed_before(Operation.CHECKOUT, stages) == []


def test_performed_before_lists_unpassed_predecessors() -> None:
    stages = _stages(software_check=StageStatus.PASSED)
    assert performed_before(Operation.SOFTWARE_CHECK, stages) == ["agent_report"]


def test_missing_steps_excludes_only_passed() -> None:
    stages = _stages(
        device_status=StageStatus.PASSED,
        agent_report=StageStatus.FAILED,
        software_check=StageStatus.NOT_DONE,
    )
    missing = {item["stage"]: item for item in missing_steps(stages)}
    assert "device_status" not in missing
    assert missing["agent_report"]["status"] == "failed"
    assert missing["software_check"]["status"] == "not_done"
    assert len(missing) == 8


def test_missing_steps_uses_stored_reason_and_actionable_hint() -> None:
    stages = _stages(
        agent_report=StageStatus.FAILED,
        software_check=StageStatus.NOT_DONE,
    )
    stages[1] = StageState(
        Stage.AGENT_REPORT,
        StageStatus.FAILED,
        reason="Report serial does not match the handover device serial.",
    )
    missing = {item["stage"]: item for item in missing_steps(stages)}
    assert "Report serial" in missing["agent_report"]["hint"]
    assert missing["software_check"]["hint"].startswith("Not done:")


def test_gaps_lists_every_not_passed_operation() -> None:
    stages = _stages(device_status=StageStatus.PASSED)
    listed = gaps(stages)
    assert len(listed) == 8
    assert listed[-1]["operation"] == "document_pushed"


def test_next_operation_is_the_first_unfinished_suggestion() -> None:
    stages = _stages(
        device_status=StageStatus.PASSED,
        agent_report=StageStatus.NOT_DONE,
    )
    assert next_operation(stages, HANDOVER_OPERATIONS) is Operation.AGENT_REPORT
    everything = [StageState(operation, StageStatus.PASSED) for operation in HANDOVER_OPERATIONS]
    assert next_operation(everything, HANDOVER_OPERATIONS) is None


def test_stage_from_key_accepts_handover_and_maintenance_keys() -> None:
    assert stage_from_key("checkout") is Stage.CHECKOUT
    assert stage_from_key("sent_out") is Operation.SENT_OUT


def test_company_normalization_ignores_case_and_punctuation() -> None:
    assert normalize_company("B.tech") == "btech"
    assert normalize_company(" B.TECH ") == "btech"
    assert company_known("B.tech")
    assert not company_known(" -- ")


def test_company_same_name_does_not_conflict() -> None:
    assert not company_conflict("B.tech", "btech")
    assert not company_conflict("B.tech", "B.TECH")


def test_company_unknown_side_does_not_conflict() -> None:
    assert not company_conflict("B.tech", None)
    assert not company_conflict(None, "Mylo")


def test_company_different_known_names_conflict() -> None:
    assert company_conflict("B.tech", "Mylo")


def test_stage_from_key_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="Unknown stage"):
        stage_from_key("not_a_stage")


def test_redaction_removes_partial_key_without_mutating_input() -> None:
    payload = {
        "hostname": "PC-01",
        "windows_activation": {
            "status": "Licensed",
            "product_name": "Windows 11 Pro",
            "partial_key": "ABCDE",
        },
    }
    redacted = redact_agent_payload(payload)

    assert "partial_key" not in redacted["windows_activation"]
    assert redacted["windows_activation"]["status"] == "Licensed"
    assert payload["windows_activation"]["partial_key"] == "ABCDE"
    assert redacted is not payload


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hostname": "PC-01"},
        {"windows_activation": None},
        {"windows_activation": "not-a-dict"},
        {"windows_activation": {}},
    ],
)
def test_redaction_tolerates_payloads_without_activation(payload: dict) -> None:
    assert redact_agent_payload(payload) == payload

