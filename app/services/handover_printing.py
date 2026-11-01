"""Automatic printing of the handover form, driven by the database.

The owner's requirement: the portal prints the handover form itself and the
``report_printed`` stage is decided by the system, not by a button.

Flow (never a database transaction around the blocking work):

1. Claim  - one short transaction claims the attempt. A partial unique index
            allows a single ``running`` attempt per handover, so two triggers
            at the same moment print once. The claim is committed.
2. Render  - outside any transaction, ``asyncio.to_thread`` fills the DOCX,
            converts it to PDF and (spooler mode) submits it. This can take a
            minute or more.
3. Record  - a second short transaction stores the outcome on the stage, in
            the attempt row and as an append-only event.

Only ``accepted`` (spooler mode) makes the stage pass. In ``pdf_only`` the
stage stays pending with "the PDF is ready" and the engineer may confirm by
hand with a reason; in ``spooler`` mode a hand confirmation is refused.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import config
from app.clients.snipeit import ServiceAccountProvider, SnipeItClient, SnipeItError
from app.db.engine import get_sessionmaker
from app.db.models.handover import Handover, PrintAttempt
from app.domain.errors import (
    HandoverError,
    HandoverNotFound,
    PrintConflict,
    PrintDocumentMissing,
    PrintUnavailable,
)
from app.domain.print_rules import (
    ALREADY_CONFIRMED_REASON,
    AUTOMATIC_ONLY_REASON,
    MANUAL_CONFIRMED_REASON,
    PRINTING_DISABLED_REASON,
    STALE_CLAIM_ERROR_CLASS,
    STALE_CLAIM_REASON,
    PrintMode,
    PrintState,
    manual_confirmation_allowed,
    manual_reason_problem,
    print_guard,
    public_reason,
    stage_result,
)
from app.domain.stages import Stage, StageStatus
from app.repositories.events import EventRepository
from app.repositories.handovers import HandoverRepository
from app.repositories.print_attempts import PrintAttemptRepository
from app.services import laptop_form, printing
from app.services.handovers import (
    HandoverDetailView,
    HandoverService,
    ensure_open,
    stage_row,
    stage_states,
)

logger = logging.getLogger("app.printing")

REPORT_PATH_HINT = "The handover has no agent report yet; run the device check first."
NO_PRINTER_REASON = (
    "No print queue is configured on this server. An administrator must set "
    "PRINT_PRINTER to a queue name from Get-Printer."
)
ALREADY_RUNNING_REASON = "A print of this handover form is already running."
ALREADY_PRINTED_REASON = (
    "The form was already sent to the printer. Use reprint to print again."
)
NO_PDF_REASON = "No rendered PDF is waiting for a manual confirmation."


# ── small value objects ──────────────────────────────────────────────────
@dataclass(frozen=True)
class PrintJob:
    """Everything the blocking pipeline needs, already detached from the DB."""

    handover_id: str
    attempt_no: int
    mode: PrintMode
    printer: str | None
    data: dict[str, Any] = field(default_factory=dict)
    snipe: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PrintStateView:
    """The state of the print of one handover, as the API reports it."""

    handover_id: uuid.UUID
    state: PrintState
    mode: PrintMode
    printer: str | None = None
    attempt_no: int = 0
    attempt_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reason: str | None = None
    pdf_available: bool = False
    manual: bool = False
    manual_reason: str | None = None
    job: dict[str, Any] | None = None


# ── mode and helpers ─────────────────────────────────────────────────────
def resolve_mode() -> PrintMode:
    """The configured print mode, read at call time (tests switch it)."""
    configured = (config.PRINT_MODE or "").strip().lower()
    if configured == PrintMode.SPOOLER.value:
        return PrintMode.SPOOLER
    if configured == PrintMode.PDF_ONLY.value:
        return PrintMode.PDF_ONLY
    # An unknown value must never silently print: fall back to the safe mode.
    logger.warning("Unknown PRINT_MODE %r; using pdf_only.", configured)
    return PrintMode.PDF_ONLY


def configured_printer() -> str | None:
    printer = (config.PRINT_PRINTER or "").strip()
    return printer or None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def _stale_cutoff() -> datetime:
    seconds = config.PRINT_TIMEOUT_SECONDS + config.PRINT_STALE_MARGIN_SECONDS
    return _utcnow() - timedelta(seconds=max(seconds, 1))


def _document_base(handover_id: uuid.UUID | str, attempt_no: int) -> str:
    """File stem built from the case id and the attempt - never user input."""
    safe_id = re.sub(r"[^A-Za-z0-9-]", "", str(handover_id))
    return f"Handover_{safe_id}_attempt{attempt_no}"


def _download_name(attempt: PrintAttempt, serial: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", serial or "handover")
    return f"handover-form-{stem}-attempt{attempt.attempt_no}.pdf"


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── the blocking pipeline (runs in a worker thread) ──────────────────────
def render_and_submit(job: PrintJob) -> dict[str, Any]:
    """Fill the form, convert to PDF, optionally submit it. Blocking!

    Returns the public result of the attempt. Raises ``LaptopFormError`` /
    ``PrintingError`` / ``PrintUnavailable`` for the caller to record.
    """
    output_dir = config.FORM_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    base = _document_base(job.handover_id, job.attempt_no)
    docx_path = os.path.join(output_dir, base + ".docx")

    if job.mode is PrintMode.SPOOLER and not job.printer:
        raise PrintUnavailable(NO_PRINTER_REASON)

    fill_result = laptop_form.fill_document(
        job.data, job.snipe, config.FORM_TEMPLATE_PATH, docx_path, job.extra
    )
    pdf_path = laptop_form.convert_to_pdf(docx_path, output_dir)
    pdf_name = os.path.basename(pdf_path)
    digest = _sha256(pdf_path)

    result: dict[str, Any] = {
        "pdf_name": pdf_name,
        "pdf_sha256": digest,
        "spooler_accepted": False,
        "job": None,
        "tokens_missing": fill_result.get("tokens_missing", []),
        "labels_filled": fill_result.get("labels_filled", 0),
    }

    if job.mode is PrintMode.SPOOLER:
        printing.run_ghostscript(pdf_path, job.printer or "")
        result["spooler_accepted"] = True
        result["printer"] = job.printer
        # "Accepted by the spooler" is not "printed on paper": snapshot the
        # queue so the page can show an honest job status.
        try:
            for entry in printing.query_jobs(job.printer or ""):
                if (entry.get("document_name") or "").startswith(base):
                    result["job"] = {
                        "job_id": entry.get("job_id"),
                        "status": entry.get("job_status"),
                    }
                    break
        except printing.PrintingError:
            result["job"] = None
    return result


# ── the service ──────────────────────────────────────────────────────────
class HandoverPrintService:
    """Claim, run and record the print of one handover form."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] | None = None
    ):
        self._explicit_factory = session_factory

    def _factory(self) -> async_sessionmaker[AsyncSession]:
        # Indirection kept as a module-level name so tests can point it at the
        # harness database without touching the process-wide engine.
        return self._explicit_factory or get_sessionmaker()

    # -- trigger ---------------------------------------------------------
    async def start(
        self,
        handover_id: uuid.UUID,
        *,
        actor: str,
        reprint: bool = False,
    ) -> PrintStateView:
        """Claim one print attempt and return its running state.

        Raises ``PrintConflict`` when the guard, the previous attempt or a
        concurrent trigger refuses the claim.
        """
        mode = resolve_mode()
        async with self._factory()() as session:
            handover = await HandoverRepository(session).get(
                handover_id, with_details=True
            )
            if handover is None:
                raise HandoverNotFound(f"Handover {handover_id} was not found.")
            ensure_open(handover)

            allowed, reason = print_guard(
                checkout_passed=_stage_passed(handover, Stage.CHECKOUT)
            )
            if not allowed:
                raise PrintConflict(reason)

            if await HandoverRepository(session).latest_agent_report(handover_id) is None:
                raise PrintConflict(REPORT_PATH_HINT)

            printer = configured_printer()
            if mode is PrintMode.SPOOLER and not printer:
                raise PrintUnavailable(NO_PRINTER_REASON)

            attempts = PrintAttemptRepository(session)
            previous = await attempts.latest(handover_id)
            if previous is not None:
                if previous.state == PrintState.RUNNING.value and previous.started_at and (
                    _as_utc(previous.started_at) >= _stale_cutoff()
                ):
                    raise PrintConflict(ALREADY_RUNNING_REASON)
                if previous.state == PrintState.ACCEPTED.value and not reprint:
                    raise PrintConflict(ALREADY_PRINTED_REASON)

            attempt = await attempts.claim(
                handover_id=handover_id,
                mode=mode,
                printer=printer if mode is PrintMode.SPOOLER else None,
                actor=actor,
                stale_before=_stale_cutoff(),
            )
            if attempt is None:
                await session.rollback()
                raise PrintConflict(ALREADY_RUNNING_REASON)

            await EventRepository(session).add(
                handover_id=handover_id,
                actor=actor,
                type="print_attempt_started",
                detail={
                    "attempt": attempt.attempt_no,
                    "mode": mode.value,
                    "printer": attempt.printer,
                    "reprint": reprint,
                },
            )
            view = _view_from(attempt, mode)
            await session.commit()
        return view

    # -- work ------------------------------------------------------------
    async def run(self, handover_id: uuid.UUID, attempt_id: uuid.UUID) -> None:
        """Run one claimed attempt end to end. Never raises."""
        try:
            job, _attempt_no = await self._build_job(handover_id, attempt_id)
            result = await asyncio.to_thread(render_and_submit, job)
        except HandoverError as exc:
            await self._record_failure(
                handover_id, attempt_id, error_class=type(exc).__name__,
                reason=str(exc),
            )
            return
        except Exception as exc:  # noqa: BLE001 - the request must never break
            logger.exception("Handover form print failed (handover=%s)", handover_id)
            await self._record_failure(
                handover_id,
                attempt_id,
                error_class=type(exc).__name__,
                reason=public_reason(str(exc)),
            )
            return

        # The attempt's own mode decides the outcome, not the current config:
        # a setting changed mid-flight must not relabel a spooled job.
        if job.mode is PrintMode.SPOOLER:
            state = PrintState.ACCEPTED
            reason = None
        else:
            state = PrintState.PDF_READY
            reason = PRINTING_DISABLED_REASON
        await self._record(
            handover_id,
            attempt_id,
            state=state,
            reason=reason,
            pdf_name=result.get("pdf_name"),
            pdf_sha256=result.get("pdf_sha256"),
            extra_detail={
                "spooler_accepted": bool(result.get("spooler_accepted")),
                "job": result.get("job"),
                "tokens_missing": result.get("tokens_missing") or [],
                "labels_filled": result.get("labels_filled") or 0,
            },
            event_type=(
                "print_attempt_accepted"
                if state is PrintState.ACCEPTED
                else "print_pdf_ready"
            ),
        )

    async def _build_job(
        self, handover_id: uuid.UUID, attempt_id: uuid.UUID
    ) -> tuple[PrintJob, int]:
        """Gather the print inputs from the database (and Snipe-IT, best effort)."""
        async with self._factory()() as session:
            handover = await HandoverRepository(session).get(
                handover_id, with_details=True
            )
            if handover is None:
                raise HandoverNotFound(f"Handover {handover_id} was not found.")
            report = await HandoverRepository(session).latest_agent_report(handover_id)
            attempt = await PrintAttemptRepository(session).get(attempt_id)
            if attempt is None:
                raise PrintConflict(ALREADY_RUNNING_REASON)
            payload = dict(report.payload) if report is not None else {}
            mode = PrintMode(attempt.mode)
            attempt_no = attempt.attempt_no
            printer = attempt.printer
            extra = _handover_extra(handover)
            snipe = {
                "asset_tag": handover.snipeit_asset_tag,
                "name": handover.recipient_snipeit_username,
                "assigned_to": handover.recipient_snipeit_username,
                "status": None,
                "location": None,
                "purchase_date": None,
                "notes": None,
            }
            recipient_id = handover.recipient_snipeit_id

        if recipient_id is not None:
            recipient = await self._recipient_record(recipient_id)
            if recipient:
                extra["recipient_name"] = recipient.get("name") or extra.get(
                    "recipient_name", ""
                )
                extra["recipient_username"] = recipient.get("username") or extra.get(
                    "recipient_username", ""
                )
                snipe["assigned_to"] = (
                    recipient.get("name") or extra.get("recipient_username") or ""
                )
                snipe["name"] = recipient.get("name") or ""

        return (
            PrintJob(
                handover_id=str(handover_id),
                attempt_no=attempt_no,
                mode=mode,
                printer=printer,
                data=payload,
                snipe=snipe,
                extra=extra,
            ),
            attempt_no,
        )

    async def _recipient_record(self, recipient_id: int) -> dict[str, Any] | None:
        """The confirmed recipient's name and username, when Snipe-IT answers."""
        if not (config.SNIPEIT_TOKEN or "").strip():
            return None
        client = SnipeItClient(
            config.SNIPEIT_URL,
            ServiceAccountProvider(config.SNIPEIT_TOKEN),
            timeout=config.SNIPEIT_TIMEOUT_SECONDS,
        )
        try:
            user = await client.get_user(recipient_id)
        except SnipeItError:
            return None
        finally:
            await client.aclose()
        return {"name": user.name, "username": user.username}

    async def _record_failure(
        self,
        handover_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        error_class: str,
        reason: str,
    ) -> None:
        safe = public_reason(reason)
        await self._record(
            handover_id,
            attempt_id,
            state=PrintState.FAILED,
            reason=safe,
            error_class=error_class,
            extra_detail={},
            event_type="print_attempt_failed",
        )

    async def _record(
        self,
        handover_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        state: PrintState,
        reason: str | None,
        pdf_name: str | None = None,
        pdf_sha256: str | None = None,
        error_class: str | None = None,
        extra_detail: dict[str, Any] | None = None,
        event_type: str,
    ) -> None:
        """Second short transaction: stage, attempt row and event."""
        try:
            async with self._factory()() as session:
                attempts = PrintAttemptRepository(session)
                attempt = await attempts.get(attempt_id)
                if attempt is None:
                    return
                await attempts.finish(
                    attempt,
                    state=state,
                    reason=reason,
                    pdf_name=pdf_name,
                    pdf_sha256=pdf_sha256,
                    error_class=error_class,
                    detail=extra_detail,
                )
                handover = await HandoverRepository(session).get(
                    handover_id, with_details=True
                )
                if handover is None:
                    await session.commit()
                    return
                row = stage_row(handover, Stage.REPORT_PRINTED)
                result = stage_result(state, reason=reason)
                row.status = result.status.value
                row.reason = result.reason
                row.actor = attempt.actor or None
                row.updated_at = _utcnow()
                row.detail = {
                    "print_state": state.value,
                    "print_mode": attempt.mode,
                    "print_printer": attempt.printer,
                    "print_attempt": attempt.attempt_no,
                    "print_started_at": _iso(attempt.started_at),
                    "print_finished_at": _iso(attempt.finished_at),
                    "print_pdf_sha256": attempt.pdf_sha256,
                    "print_pdf_name": attempt.pdf_name,
                    "print_spooler_accepted": bool(
                        (extra_detail or {}).get("spooler_accepted")
                    ),
                    "print_error_class": attempt.error_class,
                    "message": result.reason,
                }
                await EventRepository(session).add(
                    handover_id=handover_id,
                    actor=attempt.actor or "",
                    type=event_type,
                    detail={
                        "attempt": attempt.attempt_no,
                        "mode": attempt.mode,
                        "printer": attempt.printer,
                        "pdf_sha256": attempt.pdf_sha256,
                        "spooler_accepted": bool(
                            (extra_detail or {}).get("spooler_accepted")
                        ),
                        "error_class": attempt.error_class,
                        "reason": public_reason(reason) if reason else None,
                    },
                )
                await HandoverService(session).recompute_status(handover)
                await session.commit()
        except Exception:  # noqa: BLE001 - a failed record must not crash a worker
            logger.exception(
                "Could not record the print outcome (handover=%s attempt=%s)",
                handover_id,
                attempt_id,
            )

    # -- reads -----------------------------------------------------------
    async def state(self, handover_id: uuid.UUID) -> PrintStateView:
        """The current print state of one handover."""
        mode = resolve_mode()
        async with self._factory()() as session:
            handover = await HandoverRepository(session).get(
                handover_id, with_details=True
            )
            if handover is None:
                raise HandoverNotFound(f"Handover {handover_id} was not found.")
            attempts = PrintAttemptRepository(session)
            retired = await attempts.expire_stale(handover_id, _stale_cutoff())
            if retired:
                await self._mark_stale(session, handover)
            attempt = await attempts.latest(handover_id)
            await session.commit()

        if attempt is None:
            return PrintStateView(
                handover_id=handover_id, state=PrintState.IDLE, mode=mode
            )

        detail = dict(attempt.detail or {})
        view = _view_from(attempt, PrintMode(attempt.mode))
        job = None
        if (
            attempt.state == PrintState.ACCEPTED.value
            and attempt.printer
            and os.name == "nt"
        ):
            job = await asyncio.to_thread(_query_job, attempt.printer)
        return PrintStateView(
            handover_id=view.handover_id,
            state=view.state,
            mode=view.mode,
            printer=view.printer,
            attempt_no=view.attempt_no,
            attempt_id=view.attempt_id,
            started_at=view.started_at,
            finished_at=view.finished_at,
            reason=view.reason,
            pdf_available=bool(detail.get("pdf_available", attempt.pdf_name)),
            manual=bool(detail.get("manual")),
            manual_reason=detail.get("manual_reason"),
            job=job,
        )

    async def _mark_stale(self, session: AsyncSession, handover: Handover) -> None:
        """A reaped attempt must not leave the stage looking "in progress"."""
        row = stage_row(handover, Stage.REPORT_PRINTED)
        if row.status != StageStatus.PASSED.value:
            row.status = StageStatus.FAILED.value
            row.reason = STALE_CLAIM_REASON
            row.actor = None
            row.updated_at = _utcnow()
            row.detail = {
                **(row.detail or {}),
                "print_state": PrintState.FAILED.value,
                "print_error_class": STALE_CLAIM_ERROR_CLASS,
                "message": STALE_CLAIM_REASON,
            }
            await HandoverService(session).recompute_status(handover)
        await EventRepository(session).add(
            handover_id=handover.id,
            actor="",
            type="print_attempt_failed",
            detail={
                "error_class": STALE_CLAIM_ERROR_CLASS,
                "reason": STALE_CLAIM_REASON,
            },
        )

    async def pdf_path(self, handover_id: uuid.UUID) -> tuple[Path, str]:
        """The stored PDF of the last attempt, resolved from the database only."""
        async with self._factory()() as session:
            handover = await HandoverRepository(session).get(
                handover_id, with_details=False
            )
            if handover is None:
                raise HandoverNotFound(f"Handover {handover_id} was not found.")
            attempt = await PrintAttemptRepository(session).latest(handover_id)
            serial = handover.device_serial
        if attempt is None or not attempt.pdf_name:
            raise PrintDocumentMissing(NO_PDF_REASON)

        root = Path(config.FORM_OUTPUT_DIR).resolve()
        candidate = (root / Path(attempt.pdf_name).name).resolve()
        if root != candidate and root not in candidate.parents:
            # The name came from the database, but never trust it blindly.
            raise PrintDocumentMissing(NO_PDF_REASON)
        if not candidate.is_file():
            raise PrintDocumentMissing(
                "The stored PDF is no longer on the server."
            )
        return candidate, _download_name(attempt, serial)

    # -- manual confirmation (pdf_only mode only) -------------------------
    async def confirm_manually(
        self, handover_id: uuid.UUID, *, actor: str, reason: str
    ) -> HandoverDetailView:
        mode = resolve_mode()
        allowed, why = manual_confirmation_allowed(mode)
        if not allowed:
            raise PrintConflict(why)
        problem = manual_reason_problem(reason)
        if problem:
            raise PrintConflict(problem)

        async with self._factory()() as session:
            handover = await HandoverRepository(session).get(
                handover_id, with_details=True
            )
            if handover is None:
                raise HandoverNotFound(f"Handover {handover_id} was not found.")
            ensure_open(handover)
            row = stage_row(handover, Stage.REPORT_PRINTED)
            if row.status == StageStatus.PASSED.value and (
                row.detail or {}
            ).get("print_manual"):
                raise PrintConflict(ALREADY_CONFIRMED_REASON)
            attempts = PrintAttemptRepository(session)
            attempt = await attempts.latest(handover_id)
            if attempt is None or attempt.state != PrintState.PDF_READY.value:
                raise PrintConflict(NO_PDF_REASON)
            if not attempt.pdf_name:
                raise PrintConflict(NO_PDF_REASON)

            row.status = StageStatus.PASSED.value
            row.reason = None
            row.actor = actor
            row.updated_at = _utcnow()
            row.detail = {
                **(row.detail or {}),
                "print_state": PrintState.PDF_READY.value,
                "print_mode": attempt.mode,
                "print_attempt": attempt.attempt_no,
                "print_pdf_sha256": attempt.pdf_sha256,
                "print_pdf_name": attempt.pdf_name,
                "print_manual": True,
                "print_manual_reason": reason.strip(),
                "message": MANUAL_CONFIRMED_REASON,
            }
            attempt.detail = {
                **(attempt.detail or {}),
                "manual": True,
                "manual_reason": reason.strip(),
                "pdf_available": True,
            }
            await EventRepository(session).add(
                handover_id=handover_id,
                actor=actor,
                type="manual_print_confirmation",
                detail={
                    "attempt": attempt.attempt_no,
                    "reason": reason.strip(),
                    "mode": attempt.mode,
                },
            )
            await HandoverService(session).recompute_status(handover)
            view = await HandoverService(session).view(handover)
            await session.commit()
        return view


# ── module helpers ───────────────────────────────────────────────────────
def _stage_passed(handover: Handover, stage: Stage) -> bool:
    for state in stage_states(handover):
        if state.stage is stage:
            return state.status in (StageStatus.PASSED, StageStatus.SKIPPED)
    return False


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _view_from(attempt: PrintAttempt, mode: PrintMode) -> PrintStateView:
    detail = dict(attempt.detail or {})
    return PrintStateView(
        handover_id=attempt.handover_id,
        state=PrintState(attempt.state),
        mode=mode,
        printer=attempt.printer,
        attempt_no=attempt.attempt_no,
        attempt_id=attempt.id,
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        reason=public_reason(attempt.reason) if attempt.reason else None,
        pdf_available=bool(attempt.pdf_name),
        manual=bool(detail.get("manual")),
        manual_reason=detail.get("manual_reason"),
        job=None,
    )


def _handover_extra(handover: Handover) -> dict[str, Any]:
    return {
        "recipient_name": "",
        "recipient_username": handover.recipient_snipeit_username or "",
        "engineer_name": handover.engineer_name or handover.engineer_email,
        "asset_tag": handover.snipeit_asset_tag or "",
        "handover_id": str(handover.id),
        "print_date": _utcnow().strftime("%Y-%m-%d %H:%M"),
    }


def _query_job(printer: str) -> dict[str, Any] | None:
    try:
        jobs = printing.query_jobs(printer)
    except printing.PrintingError:
        return None
    if not jobs:
        return None
    first = jobs[0]
    return {"job_id": first.get("job_id"), "status": first.get("job_status")}


# ── entry points used by the router ──────────────────────────────────────
async def auto_print_after_checkout(
    handover_id: uuid.UUID, *, actor: str
) -> None:
    """Background entry point: print the form right after a successful checkout.

    Never raises and never undoes the checkout: a print failure only sets the
    ``report_printed`` stage to failed with a reason and a Retry action.
    """
    if not config.AUTO_PRINT_AFTER_CHECKOUT:
        return
    service = HandoverPrintService()
    try:
        view = await service.start(handover_id, actor=actor, reprint=False)
    except HandoverError as exc:
        logger.info(
            "Auto print skipped (handover=%s): %s", handover_id, exc
        )
        return
    except Exception:  # noqa: BLE001 - a background task must never crash
        logger.exception("Auto print could not start (handover=%s)", handover_id)
        return
    if view.attempt_id is not None:
        await service.run(handover_id, view.attempt_id)
