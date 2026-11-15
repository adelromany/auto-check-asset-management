"""Part A: operations are independent, recorded and concurrency-safe (BIZ-19)."""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models.handover import Event, HandoverStage
from app.domain.stages import HandoverStatus, Stage, StageStatus
from app.services.handovers import HandoverService

ENGINEER = "engineer@example.com"


@pytest_asyncio.fixture()
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'cases.db'}",
        connect_args={"timeout": 30},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _create(factory, serial="SN-CONCURRENT"):
    async with factory() as session:
        service = HandoverService(session)
        handover = await service.create(
            device_serial=serial,
            engineer_email=ENGINEER,
            engineer_name="Engineer",
        )
        await session.commit()
        return handover.id


async def _act(factory, handover_id, operation, actor):
    async with factory() as session:
        service = HandoverService(session)
        view = await service.confirm_manual_stage(
            handover_id, operation, actor=actor
        )
        await session.commit()
        return view


async def test_two_operations_of_one_case_run_concurrently(factory) -> None:
    handover_id = await _create(factory)

    await asyncio.gather(
        _act(factory, handover_id, Stage.DEVICE_PREPARED, "a@example.com"),
        _act(factory, handover_id, Stage.USER_SIGNED_IN, "b@example.com"),
    )

    # Each request returned its own read snapshot; assert on the stored state.
    async with factory() as session:
        service = HandoverService(session)
        view = await service.get_detail(handover_id)
    statuses = {item.stage: item for item in view.stages}
    assert statuses["device_prepared"].status == StageStatus.PASSED.value
    assert statuses["user_signed_in"].status == StageStatus.PASSED.value
    assert {statuses["device_prepared"].actor, statuses["user_signed_in"].actor} == {
        "a@example.com",
        "b@example.com",
    }


async def test_same_operation_twice_produces_one_write_and_one_event(factory) -> None:
    handover_id = await _create(factory)

    await asyncio.gather(
        *(
            _act(factory, handover_id, Stage.DEVICE_PREPARED, "a@example.com")
            for _ in range(4)
        )
    )

    async with factory() as session:
        events = list(
            (
                await session.execute(
                    select(Event).where(Event.handover_id == handover_id)
                )
            )
            .scalars()
            .all()
        )
        rows = list(
            (
                await session.execute(
                    select(HandoverStage).where(
                        HandoverStage.handover_id == handover_id,
                        HandoverStage.stage == Stage.DEVICE_PREPARED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    recorded = [
        event
        for event in events
        if event.type == "operation_recorded"
        and event.detail.get("operation") == "device_prepared"
    ]
    assert len(recorded) == 1


async def test_agent_report_records_hardware_and_software_separately(factory) -> None:
    handover_id = await _create(factory, serial="SN-EXPECTED")
    async with factory() as session:
        service = HandoverService(session)
        await service.record_agent_report(
            handover_id,
            {
                "serial": "SN-OTHER",
                "username": "bob",
                "user_domain": "TESTDOMAIN",
                "hostname": "PC-1",
                "cpu": "Intel i7",
                "ram_gb": 16,
                "disks": [{"name": "NVMe", "size_gb": 512}],
                "software_checks": [],
                "windows_activation": {"status": "Not activated", "status_code": 0},
            },
            actor=ENGINEER,
        )
        await session.commit()
        view = await service.get_detail(handover_id)

    by_stage = {item.stage: item for item in view.stages}
    assert by_stage["agent_report"].status == StageStatus.FAILED.value
    # Software is evaluated even though hardware failed.
    assert by_stage["software_check"].status == StageStatus.FAILED.value
    assert by_stage["software_check"].detail["report_serial_differs"] is True
    assert "report serial differs" in by_stage["software_check"].detail["warnings"]
    assert view.handover.status == HandoverStatus.IN_PROGRESS.value
    recorded = {
        event.detail.get("operation")
        for event in view.events
        if event.type == "operation_recorded"
    }
    assert {"agent_report", "software_check"} <= recorded


async def test_missing_domain_user_only_fills_the_recipient_hint(factory) -> None:
    handover_id = await _create(factory, serial="SN-LOCAL")
    async with factory() as session:
        service = HandoverService(session)
        await service.record_agent_report(
            handover_id,
            {
                "serial": "SN-LOCAL",
                "username": "localuser",
                "hostname": "PC-LOCAL",
                "console_user": "PC-LOCAL\\localuser",
                "cpu": "Intel i7",
                "ram_gb": 16,
                "disks": [{"name": "NVMe", "size_gb": 512}],
                "software_checks": [
                    {"id": item, "name": item, "installed": True}
                    for item in ("forticlient", "sccm", "intune", "office2021")
                ],
                "windows_activation": {"status": "Licensed", "status_code": 1},
            },
            actor=ENGINEER,
        )
        await session.commit()
        view = await service.get_detail(handover_id)

    recipient = next(item for item in view.stages if item.stage == "recipient_check")
    assert recipient.status == StageStatus.PENDING.value
    assert recipient.detail["is_local"] is True
    # The rest of the case is still workable.
    checkout = next(item for item in view.stages if item.stage == "checkout")
    assert checkout.status == StageStatus.PENDING.value


async def test_every_failure_records_exactly_one_outcome_and_event(factory) -> None:
    handover_id = await _create(factory)
    async with factory() as session:
        service = HandoverService(session)
        await service.record_operation(
            handover_id,
            Stage.CHECKOUT,
            status=StageStatus.FAILED,
            reason="Asset not assigned",
            detail={"snipeit_status": 422},
            actor=ENGINEER,
            input_checks=False,
        )
        await session.commit()
        view = await service.get_detail(handover_id)

    checkout = next(item for item in view.stages if item.stage == "checkout")
    assert checkout.status == StageStatus.FAILED.value
    assert checkout.reason == "Asset not assigned"
    events = [
        event
        for event in view.events
        if event.type == "operation_recorded"
        and event.detail.get("operation") == "checkout"
    ]
    assert len(events) == 1
    assert events[0].detail["outcome"] == "failed"
    assert events[0].detail["reason"] == "Asset not assigned"
