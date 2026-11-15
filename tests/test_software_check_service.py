"""Persistence-level software-check and override behavior."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401
from app.db.base import Base
from app.domain.errors import SoftwareCheckConflict
from app.domain.handover_rules import StageState, missing_steps
from app.domain.stages import Stage, StageStatus
from app.services.handovers import HandoverService
from app.services.software_check import SoftwareCheckService


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
    await engine.dispose()


def _report(serial="SW-1", *, missing=()):
    return {
        "serial": serial,
        "username": "recipient",
        "hostname": "WS-1",
        "user_domain": "ACME",
        "cpu": "Intel Core i7",
        "ram_gb": 16,
        "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
        "software_checks": [
            {
                "id": item,
                "name": "Office 2021" if item == "office2021" else item,
                "installed": item not in missing,
            }
            for item in ("forticlient", "sccm", "intune", "office2021")
        ],
        "windows_activation": {"status": "Licensed", "status_code": 1},
    }


async def _create(session):
    return await HandoverService(session).create(
        device_serial="SW-1", engineer_email="engineer@example.test",
        engineer_name="Engineer", ticket_ref=None,
    )


async def test_report_checks_software_and_rechecks_after_new_report(session):
    core = HandoverService(session)
    handover = await _create(session)

    await core.record_agent_report(
        handover.id, _report(missing=("office2021",)), actor="engineer@example.test"
    )
    view = await core.get_detail(handover.id)
    software = next(row for row in view.stages if row.stage == Stage.SOFTWARE_CHECK.value)
    assert software.status == StageStatus.FAILED.value
    assert "Office 2021" in software.reason

    await core.record_agent_report(
        handover.id, _report(), actor="engineer@example.test"
    )
    view = await core.get_detail(handover.id)
    assert next(row for row in view.stages if row.stage == Stage.AGENT_REPORT.value).status == StageStatus.PASSED.value
    assert next(row for row in view.stages if row.stage == Stage.SOFTWARE_CHECK.value).status == StageStatus.PASSED.value


async def test_mismatched_hardware_still_evaluates_software_and_override_is_rejected(session):
    core = HandoverService(session)
    handover = await _create(session)

    await core.record_agent_report(
        handover.id, _report("OTHER"), actor="engineer@example.test"
    )
    view = await core.get_detail(handover.id)
    software = next(row for row in view.stages if row.stage == Stage.SOFTWARE_CHECK.value)
    # Software is evaluated independently of the hardware result.
    assert software.status == StageStatus.PASSED.value
    assert software.detail["report_serial_differs"] is True
    with pytest.raises(SoftwareCheckConflict):
        await SoftwareCheckService(session).override(
            handover.id, reason="Not applicable", actor="engineer@example.test"
        )


async def test_failed_software_requires_reason_then_can_be_marked_not_done(session):
    core = HandoverService(session)
    handover = await _create(session)
    await core.record_agent_report(
        handover.id, _report(missing=("office2021",)), actor="engineer@example.test"
    )
    overrides = SoftwareCheckService(session)

    with pytest.raises(ValueError):
        await overrides.override(
            handover.id, reason="123456789", actor="engineer@example.test"
        )
    view = await overrides.override(
        handover.id, reason="Owner-approved exception", actor="engineer@example.test"
    )
    software = next(row for row in view.stages if row.stage == Stage.SOFTWARE_CHECK.value)
    assert software.status == StageStatus.NOT_DONE.value
    assert software.detail["override_reason"] == "Owner-approved exception"

    # A not-done operation remains a visible gap; it does not complete the case.
    gaps = {item["stage"] for item in missing_steps(
        [
            StageState(Stage(item.stage), StageStatus(item.status), item.reason)
            for item in view.stages
        ]
    )}
    assert Stage.SOFTWARE_CHECK.value in gaps


async def test_override_survives_a_new_report(session):
    core = HandoverService(session)
    handover = await _create(session)
    await core.record_agent_report(
        handover.id, _report(missing=("office2021",)), actor="engineer@example.test"
    )
    overrides = SoftwareCheckService(session)
    await overrides.override(
        handover.id, reason="Approved temporary exception", actor="engineer@example.test"
    )

    await core.record_agent_report(
        handover.id, _report(), actor="engineer@example.test"
    )
    view = await core.get_detail(handover.id)
    software = next(row for row in view.stages if row.stage == Stage.SOFTWARE_CHECK.value)
    assert software.status == StageStatus.NOT_DONE.value
    assert software.detail["override_reason"] == "Approved temporary exception"
