"""Table-driven tests for the pure handover domain (TST-03)."""

import pytest

from app.domain.handover_rules import StageState, can_run, derive_status, missing_steps
from app.domain.redaction import redact_agent_payload
from app.domain.stages import (
    STAGE_DEPENDENCIES,
    STAGE_ORDER,
    HandoverStatus,
    Stage,
    StageStatus,
    stage_from_key,
)


def _stages(**statuses: StageStatus) -> list[StageState]:
    """Build one state per stage, defaulting to pending."""
    return [
        StageState(stage, statuses.get(stage.value, StageStatus.PENDING))
        for stage in STAGE_ORDER
    ]


def test_stage_order_is_the_nine_fixed_stages() -> None:
    assert [stage.value for stage in STAGE_ORDER] == [
        "device_prepared",
        "user_signed_in",
        "agent_report",
        "recipient_check",
        "checkout",
        "report_printed",
        "user_signed",
        "document_scanned",
        "document_pushed",
    ]


def test_dependencies_are_known_stages_and_acyclic() -> None:
    for stage, dependencies in STAGE_DEPENDENCIES.items():
        assert stage in STAGE_ORDER
        for dependency in dependencies:
            assert dependency in STAGE_ORDER
            assert STAGE_ORDER.index(dependency) < STAGE_ORDER.index(stage)


@pytest.mark.parametrize(
    "stages,cancelled,expected",
    [
        (_stages(), False, HandoverStatus.DRAFT),
        ([], False, HandoverStatus.DRAFT),
        (
            [StageState(stage, StageStatus.PASSED) for stage in STAGE_ORDER],
            False,
            HandoverStatus.COMPLETED,
        ),
        (
            _stages(device_prepared=StageStatus.PASSED),
            False,
            HandoverStatus.IN_PROGRESS,
        ),
        (
            _stages(agent_report=StageStatus.FAILED),
            False,
            HandoverStatus.STALLED,
        ),
        (
            _stages(recipient_check=StageStatus.BLOCKED),
            False,
            HandoverStatus.STALLED,
        ),
        (
            _stages(device_prepared=StageStatus.FAILED),
            True,
            HandoverStatus.CANCELLED,
        ),
        ([], True, HandoverStatus.CANCELLED),
        (
            [StageState(stage, StageStatus.PASSED) for stage in STAGE_ORDER],
            True,
            HandoverStatus.CANCELLED,
        ),
        (
            _stages(
                device_prepared=StageStatus.PASSED,
                user_signed_in=StageStatus.PASSED,
                agent_report=StageStatus.PASSED,
                recipient_check=StageStatus.PASSED,
                checkout=StageStatus.PASSED,
                report_printed=StageStatus.PASSED,
                user_signed=StageStatus.PASSED,
                document_scanned=StageStatus.PASSED,
                document_pushed=StageStatus.FAILED,
            ),
            False,
            HandoverStatus.STALLED,
        ),
    ],
)
def test_derive_status(
    stages: list[StageState],
    cancelled: bool,
    expected: HandoverStatus,
) -> None:
    assert derive_status(stages, cancelled=cancelled) is expected


@pytest.mark.parametrize("stage", STAGE_ORDER)
def test_can_run_when_every_dependency_passed(stage: Stage) -> None:
    passed = set(STAGE_DEPENDENCIES[stage])
    stages = [
        StageState(item, StageStatus.PASSED if item in passed else StageStatus.PENDING)
        for item in STAGE_ORDER
    ]
    assert can_run(stage, stages) == (True, "")


@pytest.mark.parametrize(
    "stage", [stage for stage in STAGE_ORDER if STAGE_DEPENDENCIES[stage]]
)
def test_can_run_rejects_a_pending_dependency(stage: Stage) -> None:
    dependencies = STAGE_DEPENDENCIES[stage]
    missing = dependencies[-1]
    passed = set(dependencies) - {missing}
    stages = [
        StageState(item, StageStatus.PASSED if item in passed else StageStatus.PENDING)
        for item in STAGE_ORDER
    ]
    allowed, reason = can_run(stage, stages)
    assert allowed is False
    assert missing.value in reason
    assert "pending" in reason


@pytest.mark.parametrize("stage", STAGE_ORDER)
def test_can_run_rejects_an_already_passed_stage(stage: Stage) -> None:
    stages = [
        StageState(item, StageStatus.PASSED if item is stage else StageStatus.PENDING)
        for item in STAGE_ORDER
    ]
    assert can_run(stage, stages) == (False, "Stage already passed.")


def test_missing_steps_is_empty_when_everything_passed() -> None:
    stages = [StageState(stage, StageStatus.PASSED) for stage in STAGE_ORDER]
    assert missing_steps(stages) == []


def test_missing_steps_lists_everything_not_passed() -> None:
    stages = _stages(device_prepared=StageStatus.PASSED)
    missing = missing_steps(stages)
    assert [item["stage"] for item in missing] == [
        stage.value for stage in STAGE_ORDER if stage is not Stage.DEVICE_PREPARED
    ]
    assert all(item["status"] == "pending" for item in missing)
    assert all(item["hint"] for item in missing)


def test_missing_steps_uses_stored_reason_and_actionable_hint() -> None:
    stages = _stages(
        agent_report=StageStatus.PASSED,
        recipient_check=StageStatus.BLOCKED,
    )
    missing = {item["stage"]: item for item in missing_steps(stages)}
    recipient = missing["recipient_check"]
    assert recipient["status"] == "blocked"
    assert recipient["reason"] is None
    assert "Snipe-IT" in recipient["hint"]

    stages = _stages(
        agent_report=StageStatus.FAILED,
    )
    failed = {item["stage"]: item for item in missing_steps(stages)}["agent_report"]
    assert failed["status"] == "failed"


def test_missing_steps_keeps_the_stored_reason() -> None:
    stages = [
        StageState(
            Stage.AGENT_REPORT,
            StageStatus.FAILED,
            reason="Report serial does not match the handover device serial.",
        )
    ]
    failed = {item["stage"]: item for item in missing_steps(stages)}["agent_report"]
    assert failed["reason"] == "Report serial does not match the handover device serial."
    assert "Report serial" in failed["hint"]


def test_stage_from_key_accepts_known_keys() -> None:
    assert stage_from_key("checkout") is Stage.CHECKOUT


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
