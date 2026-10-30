"""Insert-only repository for the append-only business event trail (LOG-07).

There is deliberately no update or delete method: events are the audit trail.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Event


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
            at=at or datetime.now(timezone.utc),
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
