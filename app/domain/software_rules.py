"""Pure hardware, software and Windows activation checks for agent reports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .stages import StageStatus


@dataclass(frozen=True)
class EvaluationResult:
    status: StageStatus
    message: str
    detail: dict[str, Any]


def evaluate_hardware(
    report: dict[str, Any], expected_serial: str
) -> EvaluationResult:
    """Validate identity and required hardware fields without I/O."""
    problems: list[str] = []
    reported_value = report.get("serial")
    reported_serial = str(reported_value or "").strip()
    expected = str(expected_serial or "").strip()

    if not reported_serial:
        problems.append("Agent report did not include a serial number.")
    elif reported_serial.casefold() != expected.casefold():
        problems.extend(
            [
                "Report serial does not match the handover device serial.",
                f"Serial mismatch: device reports {reported_serial}, case expects {expected}.",
            ]
        )

    cpu = report.get("cpu")
    if not isinstance(cpu, str) or not cpu.strip():
        problems.append("CPU is missing.")

    ram = report.get("ram_gb")
    try:
        valid_ram = not isinstance(ram, bool) and float(ram) > 0
    except (TypeError, ValueError):
        valid_ram = False
    if not valid_ram:
        problems.append("RAM must be greater than 0 GB.")

    disks = report.get("disks")
    if not isinstance(disks, list) or not disks:
        problems.append("No disks were reported.")

    detail = {
        "reported_serial": reported_serial or None,
        "expected_serial": expected,
        "problems": problems,
    }
    if problems:
        return EvaluationResult(
            StageStatus.FAILED, "; ".join(problems), detail
        )
    return EvaluationResult(
        StageStatus.PASSED,
        "Hardware report matches the handover device.",
        detail,
    )


def evaluate_software(
    report: dict[str, Any], required_ids: list[str] | tuple[str, ...]
) -> EvaluationResult:
    """Require each configured program plus a licensed Windows status."""
    checks = report.get("software_checks")
    if not isinstance(checks, list) or not checks:
        message = "No software checks were reported"
        return EvaluationResult(
            StageStatus.FAILED,
            message,
            {"missing_software": [], "activation_status": _activation_text(report), "problem": message},
        )

    by_id = {
        str(check.get("id") or "").strip().casefold(): check
        for check in checks
        if isinstance(check, dict) and str(check.get("id") or "").strip()
    }
    missing: list[dict[str, str]] = []
    for required in required_ids:
        software_id = str(required).strip().casefold()
        if not software_id:
            continue
        check = by_id.get(software_id)
        if check is None or check.get("installed") is not True:
            missing.append(
                {
                    "id": software_id,
                    "name": str(
                        (check or {}).get("name") or _software_name(software_id)
                    ).strip(),
                }
            )

    activation = report.get("windows_activation")
    activation = activation if isinstance(activation, dict) else {}
    activation_text = str(activation.get("status") or "Not reported").strip()
    activation_code = activation.get("status_code")
    activation_passed = type(activation_code) is int and activation_code == 1

    messages: list[str] = []
    if missing:
        names = ", ".join(item["name"] for item in missing)
        messages.append(f"Missing required software: {names}.")
    if not activation_passed:
        messages.append(f"Windows activation is not licensed: {activation_text}.")

    detail = {
        "missing_software": missing,
        "activation_status": activation_text,
        "activation_status_code": activation_code,
    }
    if messages:
        return EvaluationResult(
            StageStatus.FAILED, " ".join(messages), detail
        )
    return EvaluationResult(
        StageStatus.PASSED,
        "Required software is installed and Windows is activated.",
        detail,
    )


def _activation_text(report: dict[str, Any]) -> str:
    activation = report.get("windows_activation")
    if not isinstance(activation, dict):
        return "Not reported"
    return str(activation.get("status") or "Not reported").strip()


def _software_name(software_id: str) -> str:
    known = {
        "forticlient": "FortiClient",
        "sccm": "SCCM",
        "intune": "Intune",
        "office2021": "Office 2021",
    }
    return known.get(software_id, software_id.replace("_", " ").replace("-", " ").title())
