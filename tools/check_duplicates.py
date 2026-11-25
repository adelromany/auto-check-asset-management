"""Read-only check for duplicate maintenance cases by normalized serial."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import config
from app.db.models.handover import Handover


async def main() -> None:
    engine = create_async_engine(config.DATABASE_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            stmt = (
                select(
                    func.lower(Handover.device_serial).label("serial_key"),
                    func.count(Handover.id).label("cnt"),
                )
                .where(Handover.kind == "maintenance")
                .group_by(func.lower(Handover.device_serial))
                .having(func.count(Handover.id) > 1)
                .order_by(func.count(Handover.id).desc())
            )
            rows = (await session.execute(stmt)).all()
            if not rows:
                print("No duplicate maintenance serials found.")
                return
            print(f"Found {len(rows)} duplicate maintenance serial(s):")
            for serial_key, cnt in rows:
                cases = (
                    await session.execute(
                        select(
                            Handover.id,
                            Handover.device_serial,
                            Handover.status,
                            Handover.maintenance_state,
                            Handover.created_at,
                        )
                        .where(
                            Handover.kind == "maintenance",
                            func.lower(Handover.device_serial) == serial_key,
                        )
                        .order_by(Handover.created_at.asc())
                    )
                ).all()
                print(f"- {serial_key}: {cnt} cases")
                for case_id, raw_serial, status, maint_state, created_at in cases:
                    print(
                        f"    id={case_id} serial={raw_serial!r} status={status} "
                        f"maintenance_state={maint_state} created_at={created_at}"
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
