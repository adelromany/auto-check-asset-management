"""0002 adds exactly one software stage to pre-existing SQLite cases."""

import asyncio

from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401
from app.db.models.handover import Handover, HandoverStage
from app.services.handovers import HandoverService


def test_software_stage_migration_handles_old_cases_and_is_repeatable(tmp_path):
    database = tmp_path / "migration.sqlite"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    alembic = Config("alembic.ini")
    alembic.attributes["sqlalchemy_url"] = url
    command.upgrade(alembic, "0001_initial")

    async def seed_old_rows():
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            service = HandoverService(session)
            statuses = ("completed", "cancelled", "draft", "in_progress")
            for index, status in enumerate(statuses):
                handover = await service.create(
                    device_serial=f"OLD-{index}",
                    engineer_email="engineer@example.test",
                    engineer_name="Engineer",
                )
                await session.execute(
                    delete(HandoverStage).where(
                        HandoverStage.handover_id == handover.id,
                        HandoverStage.stage == "software_check",
                    )
                )
                await session.execute(
                    update(Handover).where(Handover.id == handover.id).values(status=status)
                )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed_old_rows())
    command.upgrade(alembic, "head")
    command.upgrade(alembic, "head")

    async def check_rows():
        engine = create_async_engine(url)
        factory = async_sessionmaker(engine)
        async with factory() as session:
            rows = (await session.execute(
                select(Handover.status, HandoverStage.status, HandoverStage.detail)
                .join(HandoverStage, Handover.id == HandoverStage.handover_id)
                .where(HandoverStage.stage == "software_check")
            )).all()
            assert len(rows) == 4
            mapped = {case_status: (stage_status, detail) for case_status, stage_status, detail in rows}
            assert mapped["completed"][0] == "skipped"
            assert mapped["cancelled"][0] == "skipped"
            assert mapped["completed"][1]["message"] == "Added after this case was closed"
            assert mapped["draft"][0] == "pending"
            assert mapped["in_progress"][0] == "pending"
        await engine.dispose()

    asyncio.run(check_rows())
    command.downgrade(alembic, "-1")
    command.upgrade(alembic, "head")
    asyncio.run(check_rows())
