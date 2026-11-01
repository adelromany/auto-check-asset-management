"""Table-driven tests for the pure handover domain (TST-03)."""

import pytest

from app.domain.handover_rules import StageState, can_run, derive_status, missing_steps
from app.domain.print_rules import (
    AUTOMATIC_ONLY_REASON,
    CHECKOUT_REQUIRED_REASON,
    FAILED_FALLBACK_REASON,
    MANUAL_REASON_MAX_LENGTH,
    PRINTING_DISABLED_REASON,
    RUNNING_REASON,
    PrintMode,
    PrintState,
    manual_confirmation_allowed,
    manual_reason_problem,
    print_guard,
    public_reason,
    stage_result,
)
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


def test_stage_order_is_the_ten_fixed_stages() -> None:
    assert [stage.value for stage in STAGE_ORDER] == [
        "device_prepared",
        "user_signed_in",
        "agent_report",
        "software_check",
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


# -- print rules (the portal prints the form) -------------------------------


@pytest.mark.parametrize(
    "state,status,reason",
    [
        (PrintState.ACCEPTED, StageStatus.PASSED, None),
        (PrintState.PDF_READY, StageStatus.PENDING, PRINTING_DISABLED_REASON),
        (PrintState.RUNNING, StageStatus.PENDING, RUNNING_REASON),
        (PrintState.IDLE, StageStatus.PENDING, None),
        (PrintState.FAILED, StageStatus.FAILED, "spooler rejected the job"),
    ],
)
def test_print_stage_result_never_passes_on_a_failure(
    state: PrintState, status: StageStatus, reason: str | None
) -> None:
    result = stage_result(state, reason="spooler rejected the job")

    assert result.status is status
    assert result.reason == reason


def test_print_stage_result_uses_a_plain_fallback_reason() -> None:
    assert stage_result(PrintState.FAILED).reason == FAILED_FALLBACK_REASON


def test_only_a_server_without_a_printer_may_confirm_by_hand() -> None:
    assert manual_confirmation_allowed(PrintMode.PDF_ONLY) == (True, "")
    allowed, why = manual_confirmation_allowed(PrintMode.SPOOLER)
    assert allowed is False
    assert why == AUTOMATIC_ONLY_REASON


@pytest.mark.parametrize(
    "reason,problem",
    [
        ("", True),
        ("   too short  ", True),
        ("short", True),
        ("x" * (MANUAL_REASON_MAX_LENGTH + 1), True),
        ("This server has no printer.", False),
    ],
)
def test_manual_reason_must_be_a_real_reason(reason: str, problem: bool) -> None:
    assert (manual_reason_problem(reason) is not None) is problem


def test_printing_waits_for_the_checkout() -> None:
    assert print_guard(checkout_passed=True) == (True, "")
    assert print_guard(checkout_passed=False) == (False, CHECKOUT_REQUIRED_REASON)


def test_public_reason_strips_server_paths() -> None:
    cleaned = public_reason(
        r"failed to read C:\Program Files\LibreOffice\soffice.exe "
        r"and \\fileserver\share\form.docx"
    )

    assert "C:\\" not in cleaned
    assert "fileserver" not in cleaned
    assert "failed to read" in cleaned


def test_public_reason_truncates_long_output() -> None:
    cleaned = public_reason("word " * 200, limit=40)

    assert len(cleaned) <= 40
    assert cleaned.endswith("…")


def test_public_reason_never_returns_an_empty_string() -> None:
    assert public_reason("C:\\temp\\x.docx") == FAILED_FALLBACK_REASON


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
