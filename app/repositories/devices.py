"""Device-centric reads across both case kinds."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.handover import Handover
from app.db.models.maintenance import MaintenanceInfo


class DeviceRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def cases(self, serial: str | None = None) -> list[Handover]:
        statement = select(Handover).options(
            selectinload(Handover.stages),
            selectinload(Handover.events),
            selectinload(Handover.maintenance).selectinload(MaintenanceInfo.destination),
        )
        if serial is not None:
            statement = statement.where(func.lower(Handover.device_serial) == serial.strip().casefold())
        statement = statement.order_by(Handover.updated_at.desc(), Handover.created_at.desc())
        return list((await self._session.execute(statement)).scalars().unique())
