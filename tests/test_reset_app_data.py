"""Tests for tools/reset_app_data.py (Round 2, group R3)."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401  (registers every table)
from app.db.base import Base
from app.db.models.handover import Event, Handover, HandoverStage
from app.db.models.maintenance import DiagnosisCategory, MaintenanceDestination

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import reset_app_data  # noqa: E402

NOW = datetime(2026, 11, 25, 10, 0, 0)


def _url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.as_posix()}"


async def _seed_db(path: Path) -> None:
    engine = create_async_engine(_url(path))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        vendor = MaintenanceDestination(name="Vendor A", name_key="vendor a")
        session.add(vendor)
        handover = Handover(
            id=uuid.uuid4(),
            kind="handover",
            status="in_progress",
            engineer_email="engineer@example.com",
            engineer_name="Engineer",
            device_serial="SN-1",
            device_company="B.tech",
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(handover)
        session.add(
            HandoverStage(
                handover_id=handover.id,
                stage="device_status",
                status="passed",
            )
        )
        session.add(
            Event(
                handover_id=handover.id,
                actor="engineer@example.com",
                type="handover_created",
                detail={},
            )
        )
        await session.commit()
    await engine.dispose()


async def _add_reference_rows(path: Path) -> None:
    """Keep one vendor and one diagnosis reason in the database."""
    engine = create_async_engine(_url(path))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add(
            DiagnosisCategory(name="Screen", name_key="screen")
        )
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio()
async def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    await _add_reference_rows(db_path)
    docs = tmp_path / "data" / "documents"
    docs.mkdir(parents=True)
    (docs / "scan.pdf").write_bytes(b"x")

    result = await reset_app_data.reset_app_data(
        database_url=_url(db_path),
        documents_dir=docs,
        apply=False,
        project_root=tmp_path,
    )

    assert result["applied"] is False
    assert result["before"]["handovers"] == 1
    assert result["after"]["handovers"] == 1
    assert result["backup"] is None
    assert (docs / "scan.pdf").exists()
    assert not list(tmp_path.glob("data/backup-*.db"))


@pytest.mark.asyncio()
async def test_yes_clears_cases_and_keeps_reference_data(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    await _add_reference_rows(db_path)
    docs = tmp_path / "data" / "documents"
    docs.mkdir(parents=True)
    (docs / "scan.pdf").write_bytes(b"x")

    result = await reset_app_data.reset_app_data(
        database_url=_url(db_path),
        documents_dir=docs,
        apply=True,
        project_root=tmp_path,
    )

    assert result["applied"] is True
    assert result["after"]["handovers"] == 0
    assert result["after"]["handover_stages"] == 0
    assert result["after"]["events"] == 0
    assert result["after"]["maintenance_info"] == 0
    assert result["after"]["maintenance_destinations"] == 1
    assert result["after"]["diagnosis_categories"] == 1
    assert not (docs / "scan.pdf").exists()
    backups = list(tmp_path.glob("data/backup-*.db"))
    assert len(backups) == 1
    assert result["backup"] == str(backups[0])


@pytest.mark.asyncio()
async def test_vendors_flag_clears_the_vendor_list(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    docs = tmp_path / "data" / "documents"
    docs.mkdir(parents=True)

    result = await reset_app_data.reset_app_data(
        database_url=_url(db_path),
        documents_dir=docs,
        apply=True,
        vendors=True,
        project_root=tmp_path,
    )

    assert result["after"]["maintenance_destinations"] == 0


@pytest.mark.asyncio()
async def test_demo_only_removes_only_demo_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    docs = tmp_path / "data" / "documents"
    docs.mkdir(parents=True)
    import asyncio

    async def add_demo() -> None:
        engine = create_async_engine(_url(db_path))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            session.add(
                Handover(
                    id=uuid.uuid4(),
                    kind="handover",
                    status="in_progress",
                    engineer_email="engineer@example.com",
                    engineer_name="Engineer",
                    device_serial="DEMO-0001",
                    device_company="Mylo",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()
        await engine.dispose()

    await add_demo()

    result = await reset_app_data.reset_app_data(
        database_url=_url(db_path),
        documents_dir=docs,
        apply=True,
        demo_only=True,
        project_root=tmp_path,
    )

    assert result["after"]["handovers"] == 1


@pytest.mark.asyncio()
async def test_a_path_outside_the_project_is_refused(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    outside = tmp_path.parent / "outside-docs"
    outside.mkdir(exist_ok=True)

    with pytest.raises(reset_app_data.ResetRefused):
        await reset_app_data.reset_app_data(
            database_url=_url(db_path),
            documents_dir=outside,
            apply=True,
            project_root=tmp_path,
        )


@pytest.mark.asyncio()
async def test_production_is_refused_without_the_flag(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "portal.db"
    db_path.parent.mkdir(parents=True)
    await _seed_db(db_path)
    docs = tmp_path / "data" / "documents"
    docs.mkdir(parents=True)

    with pytest.raises(reset_app_data.ResetRefused):
        await reset_app_data.reset_app_data(
            database_url=_url(db_path),
            documents_dir=docs,
            apply=True,
            project_root=tmp_path,
            app_env="production",
        )
