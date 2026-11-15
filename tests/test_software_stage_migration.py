"""0002 adds one software operation; 0003 remaps the old stage statuses."""

import asyncio
import json
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


def test_software_stage_and_status_migrations_are_repeatable(tmp_path):
    database = tmp_path / "migration.sqlite"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    alembic = Config("alembic.ini")
    alembic.attributes["sqlalchemy_url"] = url
    command.upgrade(alembic, "0001_initial")

    async def seed_old_rows():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            for index, status in enumerate(
                ("completed", "cancelled", "draft", "in_progress")
            ):
                handover_id = uuid.uuid4().hex
                await connection.execute(
                    text(
                        "INSERT INTO handovers "
                        "(id, status, engineer_email, engineer_name, device_serial) "
                        "VALUES (:id, :status, 'engineer@example.test', "
                        "'Engineer', :serial)"
                    ),
                    {
                        "id": handover_id,
                        "status": status,
                        "serial": f"OLD-{index}",
                    },
                )
                # A legacy status that 0003 must fold into "failed".
                await connection.execute(
                    text(
                        "INSERT INTO handover_stages "
                        "(id, handover_id, stage, status, reason, detail, actor) "
                        "VALUES (:id, :handover_id, 'device_prepared', "
                        ":stage_status, :reason, '{}', NULL)"
                    ),
                    {
                        "id": uuid.uuid4().hex,
                        "handover_id": handover_id,
                        "stage_status": (
                            "blocked" if status == "draft" else "passed"
                        ),
                        "reason": (
                            "Needs the dock" if status == "draft" else None
                        ),
                    },
                )
        await engine.dispose()

    async def fetch_rows():
        engine = create_async_engine(url)
        async with engine.begin() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT h.status, s.status, s.detail "
                        "FROM handovers h "
                        "JOIN handover_stages s ON s.handover_id = h.id "
                        "WHERE s.stage = 'software_check'"
                    )
                )
            ).all()
            prepared = (
                await connection.execute(
                    text(
                        "SELECT h.status, s.status, s.reason "
                        "FROM handovers h "
                        "JOIN handover_stages s ON s.handover_id = h.id "
                        "WHERE s.stage = 'device_prepared' "
                        "AND h.device_serial = 'OLD-2'"
                    )
                )
            ).one()
        await engine.dispose()
        return rows, prepared

    asyncio.run(seed_old_rows())
    command.upgrade(alembic, "head")
    command.upgrade(alembic, "head")

    rows, prepared = asyncio.run(fetch_rows())
    mapped = {
        case_status: (stage_status, json.loads(detail or "{}"))
        for case_status, stage_status, detail in rows
    }
    assert len(rows) == 4
    assert mapped["completed"][0] == "not_done"
    assert mapped["cancelled"][0] == "not_done"
    assert mapped["completed"][1]["message"] == "Added after this case was closed"
    assert mapped["draft"][0] == "pending"
    assert mapped["in_progress"][0] == "pending"
    # blocked -> failed, with the stored reason kept.
    assert prepared == ("draft", "failed", "Needs the dock")

    command.downgrade(alembic, "0002_software_check")
    rows, prepared = asyncio.run(fetch_rows())
    mapped = {
        case_status: stage_status for case_status, stage_status, _ in rows
    }
    assert mapped["completed"] == "skipped"
    assert mapped["cancelled"] == "skipped"
    assert mapped["draft"] == "pending"
    # failed -> blocked on the way back.
    assert prepared == ("draft", "blocked", "Needs the dock")

    command.upgrade(alembic, "head")
    rows, _ = asyncio.run(fetch_rows())
    mapped = {
        case_status: stage_status for case_status, stage_status, _ in rows
    }
    assert mapped["completed"] == "not_done"
