"""Insert-only repository for the append-only business event trail (LOG-07).

There is deliberately no update or delete method: events are the audit trail.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Event

_clock_lock = threading.Lock()
_last_event_at: datetime | None = None


def _next_event_at() -> datetime:
    """Return a timestamp strictly later than any event written by this process.

    The Windows system clock can return the same value for two consecutive
    reads. Two events written in the same millisecond must still keep their
    insertion order, so nudge the timestamp forward by one microsecond.
    """
    global _last_event_at
    with _clock_lock:
        now = datetime.now(timezone.utc)
        if _last_event_at is not None and now <= _last_event_at:
            now = _last_event_at + timedelta(microseconds=1)
        _last_event_at = now
        return now


class EventRepository:
    """Writes and reads events for one database session."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self,
        *,
        handover_id: uuid.UUID,
        actor: str,
        type: str,
        detail: dict[str, Any] | None = None,
        at: datetime | None = None,
    ) -> Event:
        """Append one event and flush it so it gets an id."""
        event = Event(
            handover_id=handover_id,
            actor=actor,
            type=type,
            detail=detail or {},
            at=at or _next_event_at(),
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_for_handover(self, handover_id: uuid.UUID) -> list[Event]:
        """All events for a handover, oldest first."""
        result = await self._session.execute(
            select(Event)
            .where(Event.handover_id == handover_id)
            .order_by(Event.at, Event.id)
        )
        return list(result.scalars().all())
