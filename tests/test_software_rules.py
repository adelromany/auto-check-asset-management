"""Pure software and hardware verification rules for agent reports."""

import pytest

from app.domain.handover_rules import StageState, can_run, derive_status, missing_steps
from app.domain.stages import HandoverStatus, Stage, StageStatus
from app.domain.software_rules import evaluate_hardware, evaluate_software


def _report(**values):
    return {
        "serial": "SN-1",
        "cpu": "Intel Core i7",
        "ram_gb": 16,
        "disks": [{"size_gb": 512, "type": "SSD"}],
        "software_checks": [
            {"id": "office2021", "name": "Office", "installed": True},
            {"id": "forticlient", "name": "FortiClient", "installed": True},
        ],
        "windows_activation": {"status": "Licensed", "status_code": 1},
        **values,
    }


@pytest.mark.parametrize(
    ("report", "expected_problem"),
    [
        (_report(), None),
        (_report(serial=" sn-2 "), "Serial mismatch: device reports sn-2, case expects SN-1"),
        (_report(cpu="  "), "CPU is missing"),
        (_report(ram_gb=0), "RAM must be greater than 0 GB"),
        (_report(disks=[]), "No disks were reported"),
        (_report(cpu="", ram_gb=-1, disks=[]), "CPU is missing"),
    ],
)
def test_evaluate_hardware_reports_all_failures(report, expected_problem) -> None:
    result = evaluate_hardware(report, "SN-1")

    if expected_problem is None:
        assert result.status is StageStatus.PASSED
        assert result.message == "Hardware report matches the handover device."
    else:
        assert result.status is StageStatus.FAILED
        assert expected_problem in result.message
    if report.get("cpu") == "" and report.get("ram_gb") == -1:
        assert "RAM must be greater than 0 GB" in result.message
        assert "No disks were reported" in result.message


@pytest.mark.parametrize(
    ("checks", "activation", "expected_status", "message_parts"),
    [
        (
            [
                {"id": "OFFICE2021", "name": "Office", "installed": True},
                {"id": "FortiClient", "name": "FortiClient", "installed": True},
            ],
            {"status": "Licensed", "status_code": 1},
            StageStatus.PASSED,
            (),
        ),
        (
            [{"id": "office2021", "name": "Office", "installed": False}],
            {"status": "Notification mode", "status_code": 0},
            StageStatus.FAILED,
            ("FortiClient", "Notification mode"),
        ),
        ([], {"status": "Licensed", "status_code": 1}, StageStatus.FAILED,
         ("No software checks were reported",)),
        (
            [{"id": "office2021", "name": "Office", "installed": True}],
            {"status": "Unlicensed", "status_code": 0},
            StageStatus.FAILED,
            ("FortiClient", "Unlicensed"),
        ),
    ],
)
def test_evaluate_software_lists_missing_programs_and_activation(
    checks, activation, expected_status, message_parts
) -> None:
    result = evaluate_software(
        {"software_checks": checks, "windows_activation": activation},
        ["forticlient", "office2021"],
    )

    assert result.status is expected_status
    for part in message_parts:
        assert part in result.message


def test_evaluate_software_requires_activation_code_one() -> None:
    result = evaluate_software(
        {
            "software_checks": [
                {"id": "office2021", "name": "Office", "installed": True},
                {"id": "forticlient", "name": "FortiClient", "installed": True},
            ],
            "windows_activation": {"status": "Grace", "status_code": 0},
        },
        ["office2021", "forticlient"],
    )

    assert result.status is StageStatus.FAILED
    assert "Grace" in result.message


def test_skipped_software_stage_satisfies_completion_and_dependencies() -> None:
    states = [StageState(stage, StageStatus.PASSED) for stage in Stage]
    states = [
        StageState(stage, StageStatus.SKIPPED)
        if stage is Stage.SOFTWARE_CHECK
        else state
        for stage, state in zip(Stage, states)
    ]

    assert derive_status(states) is HandoverStatus.COMPLETED
    assert all(item["stage"] != Stage.SOFTWARE_CHECK.value for item in missing_steps(states))
    allowed, reason = can_run(
        Stage.CHECKOUT,
        [
            StageState(stage, StageStatus.SKIPPED if stage in {
                Stage.RECIPIENT_CHECK, Stage.SOFTWARE_CHECK
            } else StageStatus.PENDING if stage is Stage.CHECKOUT
            else StageStatus.PASSED)
            for stage in Stage
        ],
    )
    assert allowed, reason
