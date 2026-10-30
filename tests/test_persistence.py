"""Phase 1 persistence tests: migration, constraints, laziness, event trail."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models.handover import Handover
from app.repositories.events import EventRepository

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "handovers",
    "handover_stages",
    "agent_reports",
    "documents",
    "events",
}


def _alembic_config(url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.attributes["sqlalchemy_url"] = url
    return config


def _upgrade(url: str) -> None:
    command.upgrade(_alembic_config(url), "head")


@pytest.fixture()
def sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{(tmp_path / 'handover.db').as_posix()}"


def _handover(serial: str, status: str) -> Handover:
    return Handover(
        engineer_email="engineer@example.com",
        engineer_name="Engineer",
        device_serial=serial,
        status=status,
    )


def test_migration_creates_all_tables(sqlite_url: str) -> None:
    _upgrade(sqlite_url)

    async def table_names() -> set[str]:
        engine = create_async_engine(sqlite_url)
        try:
            async with engine.connect() as connection:
                return set(
                    await connection.run_sync(
                        lambda sync_connection: inspect(sync_connection).get_table_names()
                    )
                )
        finally:
            await engine.dispose()

    assert EXPECTED_TABLES <= asyncio.run(table_names())


def test_migration_downgrades_cleanly(sqlite_url: str) -> None:
    config = _alembic_config(sqlite_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")

    async def table_names() -> set[str]:
        engine = create_async_engine(sqlite_url)
        try:
            async with engine.connect() as connection:
                return set(
                    await connection.run_sync(
                        lambda sync_connection: inspect(sync_connection).get_table_names()
                    )
                )
        finally:
            await engine.dispose()

    assert not EXPECTED_TABLES & asyncio.run(table_names())


def test_active_handover_index_is_partial(sqlite_url: str) -> None:
    _upgrade(sqlite_url)

    async def index_sql() -> str:
        engine = create_async_engine(sqlite_url)
        try:
            async with engine.connect() as connection:
                result = await connection.execute(
                    text(
                        "SELECT sql FROM sqlite_master "
                        "WHERE type = 'index' AND name = :name"
                    ),
                    {"name": "uq_handovers_active_device_serial"},
                )
                return result.scalar_one()
        finally:
            await engine.dispose()

    sql = asyncio.run(index_sql())
    assert "WHERE" in sql
    assert "completed" in sql
    assert "cancelled" in sql


async def test_second_active_handover_for_same_serial_is_rejected(
    sqlite_url: str,
) -> None:
    # Alembic's env.py calls asyncio.run(), so run it outside the test loop.
    await asyncio.to_thread(_upgrade, sqlite_url)
    engine = create_async_engine(sqlite_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            session.add(_handover("SN-1", "in_progress"))
            await session.commit()

        async with session_factory() as session:
            session.add(_handover("SN-1", "draft"))
            with pytest.raises(IntegrityError):
                await session.commit()

        # Completing the first handover frees the serial for a new one.
        async with session_factory() as session:
            first = (await session.execute(select(Handover))).scalars().one()
            first.status = "completed"
            await session.commit()

        async with session_factory() as session:
            session.add(_handover("SN-1", "in_progress"))
            await session.commit()
    finally:
        await engine.dispose()


async def test_events_are_append_only_and_ordered(sqlite_url: str) -> None:
    await asyncio.to_thread(_upgrade, sqlite_url)
    engine = create_async_engine(sqlite_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            handover = _handover("SN-2", "draft")
            session.add(handover)
            await session.flush()

            repository = EventRepository(session)
            await repository.add(
                handover_id=handover.id,
                actor="engineer@example.com",
                type="handover_created",
                detail={"device_serial": "SN-2"},
            )
            await repository.add(
                handover_id=handover.id,
                actor="engineer@example.com",
                type="stage_confirmed",
                detail={"stage": "device_prepared"},
            )
            await session.commit()

        async with session_factory() as session:
            events = await EventRepository(session).list_for_handover(handover.id)
            assert [event.type for event in events] == [
                "handover_created",
                "stage_confirmed",
            ]
    finally:
        await engine.dispose()


def test_event_repository_has_no_update_or_delete() -> None:
    public_methods = {
        name for name in dir(EventRepository) if not name.startswith("_")
    }
    assert public_methods == {"add", "list_for_handover"}


def test_importing_main_does_not_touch_the_database(tmp_path: Path) -> None:
    db_path = tmp_path / "not-created.db"
    environment = dict(os.environ)
    environment["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
    probe = (
        "import main, app.db.engine as engine;"
        "print(engine._engine is None and engine._sessionmaker is None)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"
    assert not db_path.exists()


def test_make_client_can_be_called_twice_in_one_test(make_client) -> None:
    first, _ = make_client()
    second, _ = make_client(SNIPEIT_TOKEN="dummy")
    assert first is not second
    assert second.get("/api/health").status_code == 200


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL not exercised"
)
def test_migration_runs_on_postgres() -> None:
    _upgrade(os.environ["TEST_DATABASE_URL"])
