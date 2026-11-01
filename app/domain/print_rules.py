"""Pure rules for the automatic handover-form print (no I/O, no clock).

The portal prints the handover form itself. Whether the ``report_printed``
stage passes is therefore decided from the print outcome, never by a button.
Everything here is a pure function so the decision is testable without a
printer, a database or a framework (ARC-01).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .stages import StageStatus


class PrintMode(StrEnum):
    """How this server produces the form.

    ``spooler`` submits the rendered form to a Windows print queue.
    ``pdf_only`` renders and stores the PDF but prints nothing (servers that
    have no printer, e.g. a Linux/EC2 test instance).
    """

    SPOOLER = "spooler"
    PDF_ONLY = "pdf_only"


class PrintState(StrEnum):
    """State of one print attempt, as the page and the API report it."""

    IDLE = "idle"  # nothing attempted yet
    RUNNING = "running"  # claimed, blocking work in progress
    ACCEPTED = "accepted"  # spooler accepted the job (paper not confirmed)
    FAILED = "failed"
    PDF_READY = "pdf_ready"  # pdf_only mode: file produced, nothing printed


MANUAL_REASON_MIN_LENGTH = 10
MANUAL_REASON_MAX_LENGTH = 500

PRINTING_DISABLED_REASON = (
    "Printing is disabled on this server; the PDF is ready"
)
AUTOMATIC_ONLY_REASON = "Printing is automatic"
RUNNING_REASON = "Printing in progress."
FAILED_FALLBACK_REASON = "The handover form was not printed."
MANUAL_CONFIRMED_REASON = "Confirmed manually (no printer)."
ALREADY_CONFIRMED_REASON = "This PDF was already confirmed."
STALE_CLAIM_REASON = "The print attempt stopped responding and was reclaimed."
STALE_CLAIM_ERROR_CLASS = "StaleClaim"
CHECKOUT_REQUIRED_REASON = (
    "Printing is allowed only after the checkout stage has passed."
)


@dataclass(frozen=True)
class PrintStageResult:
    """What one print outcome means for the ``report_printed`` stage."""

    status: StageStatus
    reason: str | None


def stage_result(state: PrintState, *, reason: str | None = None) -> PrintStageResult:
    """Turn one print outcome into the stage result.

    Only an outcome the print system accepted (or a PDF produced on a server
    that cannot print) releases the stage; every failure is an explicit
    ``failed`` with a plain reason, never a silent pass.
    """
    if state is PrintState.ACCEPTED:
        return PrintStageResult(StageStatus.PASSED, None)
    if state is PrintState.PDF_READY:
        return PrintStageResult(StageStatus.PENDING, PRINTING_DISABLED_REASON)
    if state is PrintState.RUNNING:
        return PrintStageResult(StageStatus.PENDING, RUNNING_REASON)
    if state is PrintState.IDLE:
        return PrintStageResult(StageStatus.PENDING, None)
    return PrintStageResult(StageStatus.FAILED, reason or FAILED_FALLBACK_REASON)


def manual_confirmation_allowed(mode: PrintMode) -> tuple[bool, str]:
    """A manual "it was printed" claim is only meaningful where nothing prints.

    In ``spooler`` mode the stage is decided by the spooler, so a hand
    confirmation would put a false claim on the audit trail.
    """
    if mode is PrintMode.PDF_ONLY:
        return True, ""
    return False, AUTOMATIC_ONLY_REASON


def manual_reason_problem(reason: str | None) -> str | None:
    """Return a plain message when a manual confirmation reason is unusable."""
    text = (reason or "").strip()
    if len(text) < MANUAL_REASON_MIN_LENGTH:
        return (
            "A reason of at least "
            f"{MANUAL_REASON_MIN_LENGTH} characters is required."
        )
    if len(text) > MANUAL_REASON_MAX_LENGTH:
        return (
            "The reason must be at most "
            f"{MANUAL_REASON_MAX_LENGTH} characters."
        )
    return None


def print_guard(*, checkout_passed: bool) -> tuple[bool, str]:
    """PROPOSED (D-70): the paper must show the assigned device and recipient.

    The stage DAG is intentionally unchanged; this is a service-level guard so
    the dependency question stays with the owner (Q-17).
    """
    if checkout_passed:
        return True, ""
    return False, CHECKOUT_REQUIRED_REASON


def is_terminal_failure(state: PrintState) -> bool:
    """States from which an explicit reprint may start a new attempt."""
    return state in (PrintState.FAILED, PrintState.ACCEPTED, PrintState.PDF_READY)


_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z]:\\[^\s,;'\")]*"),          # C:\Program Files\...
    re.compile(r"\\\\[^\s,;'\")]*"),                 # \\server\share
    re.compile(r"(?<![\w.])/(?:[^\s,;'\")/]+/)+[^\s,;'\")]*"),  # /usr/bin/x
    re.compile(r"\b[\w.-]+\\[\w.-]+\\[^\s,;'\")]*"),  # relative Windows paths
)


def public_reason(text: str | None, *, limit: int = 300) -> str:
    """A message that is safe to show an engineer and to store as evidence.

    Tool output (Ghostscript, LibreOffice, PowerShell) can contain server paths
    and command lines. Those are removed here, once, for every response and
    every event; what remains is the plain reason.
    """
    cleaned = " ".join((text or "").split())
    for pattern in _PATH_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" .,;:-")
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned or FAILED_FALLBACK_REASON


__all__ = [
    "ALREADY_CONFIRMED_REASON",
    "AUTOMATIC_ONLY_REASON",
    "CHECKOUT_REQUIRED_REASON",
    "FAILED_FALLBACK_REASON",
    "MANUAL_CONFIRMED_REASON",
    "MANUAL_REASON_MAX_LENGTH",
    "MANUAL_REASON_MIN_LENGTH",
    "PRINTING_DISABLED_REASON",
    "PrintMode",
    "PrintStageResult",
    "PrintState",
    "RUNNING_REASON",
    "STALE_CLAIM_ERROR_CLASS",
    "STALE_CLAIM_REASON",
    "is_terminal_failure",
    "manual_confirmation_allowed",
    "manual_reason_problem",
    "print_guard",
    "public_reason",
    "stage_result",
]
