"""Queries for stored evidence documents (ARC-02)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.handover import Document


class DocumentRepository:
    """Data access for documents; the service owns the filesystem."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, document: Document) -> Document:
        self._session.add(document)
        await self._session.flush()
        return document

    async def latest_for_handover(
        self, handover_id: uuid.UUID
    ) -> Document | None:
        result = await self._session.execute(
            select(Document)
            .where(Document.handover_id == handover_id)
            .order_by(Document.uploaded_at.desc(), Document.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_handover(
        self, handover_id: uuid.UUID
    ) -> list[Document]:
        result = await self._session.execute(
            select(Document)
            .where(Document.handover_id == handover_id)
            .order_by(Document.uploaded_at, Document.id)
        )
        return list(result.scalars().all())
