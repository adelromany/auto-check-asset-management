"""Phase 2 service tests against an in-memory SQLite database."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (registers every table on Base.metadata)
from app.db.base import Base
from app.db.models.handover import AgentReport
from app.domain.errors import (
    HandoverAlreadyExists,
    HandoverCancelled,
    HandoverCompleted,
    HandoverNotFound,
    InvalidStage,
    ManualStageRequired,
    StageNotRunnable,
)
from app.domain.stages import STAGE_ORDER, HandoverStatus, Stage, StageStatus
from app.services.handovers import (
    SERIAL_MISMATCH_REASON,
    SERIAL_MISSING_REASON,
    HandoverService,
)

ENGINEER = "engineer@example.com"


@pytest_asyncio.fixture()
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        yield db_session
    await engine.dispose()


@pytest_asyncio.fixture()
async def service(session):
    return HandoverService(session)


async def _create(service: HandoverService, serial: str = "SN-1", **kwargs):
    return await service.create(
        device_serial=serial,
        engineer_email=kwargs.pop("engineer_email", ENGINEER),
        engineer_name=kwargs.pop("engineer_name", "Engineer"),
        ticket_ref=kwargs.pop("ticket_ref", "T-100"),
        **kwargs,
    )


def _stage(handover, stage: Stage):
    return next(row for row in handover.stages if row.stage == stage.value)


async def test_create_makes_nine_pending_stages_and_one_event(service) -> None:
    handover = await _create(service)

    assert handover.status == HandoverStatus.DRAFT.value
    assert handover.device_serial == "SN-1"
    assert handover.ticket_ref == "T-100"
    assert handover.engineer_email == ENGINEER
    assert handover.closed_at is None
    assert [row.stage for row in handover.stages] == [
        stage.value for stage in STAGE_ORDER
    ]
    assert all(row.status == StageStatus.PENDING.value for row in handover.stages)

    view = await service.get_detail(handover.id)
    assert [event.type for event in view.events] == ["handover_created"]
    assert view.events[0].actor == ENGINEER
    assert len(view.missing_steps) == 10


async def test_create_strips_serial_and_blank_ticket(service) -> None:
    handover = await _create(service, serial="  SN-9  ", ticket_ref="   ")
    assert handover.device_serial == "SN-9"
    assert handover.ticket_ref is None


async def test_second_active_handover_for_serial_is_rejected(service) -> None:
    await _create(service, serial="SN-DUP")

    with pytest.raises(HandoverAlreadyExists):
        await _create(service, serial="SN-DUP")


async def test_cancelled_handover_frees_the_serial(service) -> None:
    first = await _create(service, serial="SN-FREE")
    await service.cancel(first.id, actor=ENGINEER)

    second = await _create(service, serial="SN-FREE")
    assert second.id != first.id


async def test_confirm_manual_stage_passes_and_writes_an_event(service) -> None:
    handover = await _create(service)

    view = await service.confirm_manual_stage(
        handover.id, "device_prepared", actor=ENGINEER
    )

    assert view.handover.status == HandoverStatus.IN_PROGRESS.value
    row = next(item for item in view.stages if item.stage == "device_prepared")
    assert row.status == StageStatus.PASSED.value
    assert row.actor == ENGINEER
    assert [event.type for event in view.events] == [
        "handover_created",
        "stage_confirmed",
    ]
    assert view.events[-1].detail == {"stage": "device_prepared"}


async def test_confirm_rejects_a_pending_dependency(service) -> None:
    handover = await _create(service)

    with pytest.raises(StageNotRunnable) as error:
        await service.confirm_manual_stage(
            handover.id, Stage.USER_SIGNED_IN, actor=ENGINEER
        )

    assert "device_prepared" in error.value.reason
    assert "pending" in error.value.reason


async def test_confirm_rejects_an_already_passed_stage(service) -> None:
    handover = await _create(service)
    await service.confirm_manual_stage(handover.id, Stage.DEVICE_PREPARED, actor=ENGINEER)

    with pytest.raises(StageNotRunnable) as error:
        await service.confirm_manual_stage(
            handover.id, Stage.DEVICE_PREPARED, actor=ENGINEER
        )
    assert "already passed" in error.value.reason


@pytest.mark.parametrize(
    "stage",
    [Stage.AGENT_REPORT, Stage.RECIPIENT_CHECK, Stage.CHECKOUT,
     Stage.DOCUMENT_SCANNED, Stage.DOCUMENT_PUSHED],
)
async def test_confirm_rejects_non_manual_stages(service, stage: Stage) -> None:
    handover = await _create(service)

    with pytest.raises(ManualStageRequired):
        await service.confirm_manual_stage(handover.id, stage, actor=ENGINEER)


async def test_confirm_rejects_unknown_stage_names(service) -> None:
    handover = await _create(service)

    with pytest.raises(InvalidStage):
        await service.confirm_manual_stage(handover.id, "not_a_stage", actor=ENGINEER)


async def test_confirm_report_printed_waits_for_the_agent_report(service) -> None:
    handover = await _create(service)
    await service.confirm_manual_stage(handover.id, Stage.DEVICE_PREPARED, actor=ENGINEER)

    with pytest.raises(StageNotRunnable) as error:
        await service.confirm_manual_stage(
            handover.id, Stage.REPORT_PRINTED, actor=ENGINEER
        )
    assert "agent_report" in error.value.reason


async def test_cancel_marks_cancelled_and_closes(service) -> None:
    handover = await _create(service)

    view = await service.cancel(handover.id, actor=ENGINEER)

    assert view.handover.status == HandoverStatus.CANCELLED.value
    assert view.handover.closed_at is not None
    assert view.events[-1].type == "handover_cancelled"
    assert view.events[-1].actor == ENGINEER


async def test_cancel_is_idempotent_and_does_not_duplicate_events(service) -> None:
    handover = await _create(service)
    await service.cancel(handover.id, actor=ENGINEER)

    view = await service.cancel(handover.id, actor=ENGINEER)

    assert view.handover.status == HandoverStatus.CANCELLED.value
    assert [event.type for event in view.events].count("handover_cancelled") == 1


async def test_cancelled_handover_rejects_further_work(service) -> None:
    handover = await _create(service)
    await service.cancel(handover.id, actor=ENGINEER)

    with pytest.raises(HandoverCancelled):
        await service.confirm_manual_stage(
            handover.id, Stage.DEVICE_PREPARED, actor=ENGINEER
        )


async def test_recompute_status_completes_when_all_stages_pass(service) -> None:
    handover = await _create(service)
    handover = await service.get(handover.id)
    for row in handover.stages:
        row.status = StageStatus.PASSED.value

    status = await service.recompute_status(handover)

    assert status is HandoverStatus.COMPLETED
    assert handover.status == HandoverStatus.COMPLETED.value
    assert handover.closed_at is not None


async def test_completed_handover_rejects_cancel_and_confirm(service) -> None:
    handover = await _create(service)
    handover = await service.get(handover.id)
    for row in handover.stages:
        row.status = StageStatus.PASSED.value
    await service.recompute_status(handover)

    with pytest.raises(HandoverCompleted):
        await service.cancel(handover.id, actor=ENGINEER)
    with pytest.raises(HandoverCompleted):
        await service.confirm_manual_stage(
            handover.id, Stage.DEVICE_PREPARED, actor=ENGINEER
        )


async def test_agent_report_with_matching_serial_passes_stage_three(
    service, session
) -> None:
    handover = await _create(service, serial="SN-MATCH")
    payload = {
        "serial": "SN-MATCH",
        "username": "alice",
        "user_domain": "TESTDOMAIN",
        "cpu": "Intel Core i7",
        "ram_gb": 16,
        "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
        "software_checks": [
            {"id": software_id, "name": software_id, "installed": True}
            for software_id in ("forticlient", "sccm", "intune", "office2021")
        ],
        "windows_activation": {
            "status": "Licensed",
            "status_code": 1,
            "product_name": "Windows 11 Pro",
            "partial_key": "ABCDE",
        },
    }

    await service.record_agent_report(handover.id, payload, actor=ENGINEER)

    view = await service.get_detail(handover.id)
    stage = next(item for item in view.stages if item.stage == "agent_report")
    assert stage.status == StageStatus.PASSED.value
    assert stage.reason is None
    assert view.handover.recipient_reported_username == "alice"
    assert view.handover.status == HandoverStatus.IN_PROGRESS.value

    report = (await session.execute(select(AgentReport))).scalars().one()
    assert report.payload["windows_activation"]["status"] == "Licensed"
    assert "partial_key" not in report.payload["windows_activation"]
    assert "ABCDE" not in str(report.payload)

    assert view.events[-1].type == "agent_report_received"
    assert view.events[-1].detail["matched"] is True


async def test_agent_report_with_other_serial_fails_stage_three(service) -> None:
    handover = await _create(service, serial="SN-EXPECTED")

    await service.record_agent_report(
        handover.id,
        {
            "serial": "SN-OTHER",
            "username": "bob",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
            "software_checks": [],
            "windows_activation": {"status": "Licensed", "status_code": 1},
        },
        actor=ENGINEER,
    )

    view = await service.get_detail(handover.id)
    stage = next(item for item in view.stages if item.stage == "agent_report")
    assert stage.status == StageStatus.FAILED.value
    assert stage.reason == SERIAL_MISMATCH_REASON
    assert view.handover.status == HandoverStatus.STALLED.value
    missing = {item["stage"]: item for item in view.missing_steps}
    assert missing["agent_report"]["status"] == "failed"
    assert SERIAL_MISMATCH_REASON in missing["agent_report"]["hint"]
    assert view.events[-1].detail["matched"] is False


async def test_agent_report_without_serial_fails_with_a_clear_reason(service) -> None:
    handover = await _create(service, serial="SN-EXPECTED")

    await service.record_agent_report(
        handover.id,
        {
            "username": "bob",
            "cpu": "Intel Core i7",
            "ram_gb": 16,
            "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
            "software_checks": [],
            "windows_activation": {"status": "Licensed", "status_code": 1},
        },
        actor=ENGINEER,
    )

    view = await service.get_detail(handover.id)
    stage = next(item for item in view.stages if item.stage == "agent_report")
    assert stage.status == StageStatus.FAILED.value
    assert stage.reason == SERIAL_MISSING_REASON


async def test_agent_report_does_not_overwrite_an_engineer_username(
    service,
) -> None:
    handover = await _create(service)
    await service.record_agent_report(
        handover.id, {"serial": "SN-1", "username": "reported"}, actor=ENGINEER
    )
    await service.record_agent_report(
        handover.id, {"serial": "SN-1", "username": "reported-again"}, actor=ENGINEER
    )

    view = await service.get_detail(handover.id)
    assert view.handover.recipient_reported_username == "reported-again"


async def test_get_unknown_handover_raises(service) -> None:
    with pytest.raises(HandoverNotFound):
        await service.get(uuid.uuid4())


async def test_list_paginates_and_filters(service) -> None:
    first = await _create(service, serial="SN-A")
    second = await _create(service, serial="SN-B")
    await service.cancel(second.id, actor=ENGINEER)

    page_one, total = await service.list(page=1, page_size=1)
    page_two, _ = await service.list(page=2, page_size=1)

    assert total == 2
    assert len(page_one) == 1
    assert len(page_two) == 1
    assert {page_one[0].id, page_two[0].id} == {first.id, second.id}

    cancelled, cancelled_total = await service.list(
        status=HandoverStatus.CANCELLED.value
    )
    assert cancelled_total == 1
    assert cancelled[0].id == second.id

    by_engineer, engineer_total = await service.list(engineer=ENGINEER)
    assert engineer_total == 2

    future = datetime.now(timezone.utc) + timedelta(days=1)
    _, future_total = await service.list(created_from=future)
    assert future_total == 0
