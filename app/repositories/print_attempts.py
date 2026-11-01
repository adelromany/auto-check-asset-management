"""Data access for print attempts.

The claim is the concurrency point of the whole print flow: a partial unique
index (``uq_print_attempts_running``) lets at most one ``running`` attempt exist
per handover, so the loser of a race gets an IntegrityError instead of a second
copy of the paper.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import PrintAttempt
from app.domain.print_rules import (
    PrintMode,
    PrintState,
    STALE_CLAIM_ERROR_CLASS,
    STALE_CLAIM_REASON,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PrintAttemptRepository:
    """Reads and writes the print attempts of one handover."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def latest(self, handover_id: uuid.UUID) -> PrintAttempt | None:
        result = await self._session.execute(
            select(PrintAttempt)
            .where(PrintAttempt.handover_id == handover_id)
            .order_by(PrintAttempt.attempt_no.desc(), PrintAttempt.started_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get(self, attempt_id: uuid.UUID) -> PrintAttempt | None:
        return await self._session.get(PrintAttempt, attempt_id)

    async def next_attempt_no(self, handover_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(PrintAttempt.attempt_no)
            .where(PrintAttempt.handover_id == handover_id)
            .order_by(PrintAttempt.attempt_no.desc())
            .limit(1)
        )
        highest = result.scalars().first()
        return (highest or 0) + 1

    async def claim(
        self,
        *,
        handover_id: uuid.UUID,
        mode: PrintMode,
        printer: str | None,
        actor: str,
        stale_before: datetime,
    ) -> PrintAttempt | None:
        """Insert a ``running`` attempt, or return ``None`` if one is in flight.

        A claim older than ``stale_before`` is first retired, so a crashed or
        killed process cannot block the form for ever.
        """
        await self.expire_stale(handover_id, stale_before)

        attempt = PrintAttempt(
            handover_id=handover_id,
            attempt_no=await self.next_attempt_no(handover_id),
            mode=mode.value,
            printer=printer,
            state=PrintState.RUNNING.value,
            actor=actor,
            started_at=_utcnow(),
            detail={},
        )
        self._session.add(attempt)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None
        return attempt

    async def expire_stale(
        self, handover_id: uuid.UUID, stale_before: datetime
    ) -> int:
        """Retire ``running`` attempts older than the cutoff."""
        result = await self._session.execute(
            update(PrintAttempt)
            .where(
                PrintAttempt.handover_id == handover_id,
                PrintAttempt.state == PrintState.RUNNING.value,
                PrintAttempt.started_at < stale_before,
            )
            .values(
                state=PrintState.FAILED.value,
                finished_at=_utcnow(),
                error_class=STALE_CLAIM_ERROR_CLASS,
                reason=STALE_CLAIM_REASON,
            )
            # The rows are not used afterwards, and SQLite hands back naive
            # datetimes, so letting the ORM compare them with an aware cutoff
            # would raise TypeError. Synchronize nothing.
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def finish(
        self,
        attempt: PrintAttempt,
        *,
        state: PrintState,
        reason: str | None = None,
        pdf_name: str | None = None,
        pdf_sha256: str | None = None,
        error_class: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> PrintAttempt:
        """Record the outcome of one attempt (second short transaction)."""
        attempt.state = state.value
        attempt.reason = reason
        attempt.pdf_name = pdf_name or attempt.pdf_name
        attempt.pdf_sha256 = pdf_sha256 or attempt.pdf_sha256
        attempt.error_class = error_class
        attempt.finished_at = _utcnow()
        if detail:
            attempt.detail = {**(attempt.detail or {}), **detail}
        await self._session.flush()
        return attempt

    async def delete_for_handover(self, handover_id: uuid.UUID) -> None:
        """Test helper: forget the attempts of one handover."""
        await self._session.execute(
            delete(PrintAttempt).where(PrintAttempt.handover_id == handover_id)
        )
