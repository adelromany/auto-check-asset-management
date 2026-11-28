"""Recurring lookup and automatic linking for recipients not yet in Snipe-IT."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app import config
from app.clients.snipeit import SnipeItClient
from app.db.models.handover import Handover
from app.domain.catalog import Operation
from app.domain.company_rules import company_conflict
from app.domain.stages import StageStatus
from app.repositories.events import EventRepository
from app.services.handovers import HandoverService
from app.services.snipeit_ops import SnipeItHandoverService

log = logging.getLogger(__name__)
OPEN = ("draft", "in_progress", "stalled")


def username_from_device(value: str | None) -> str:
    """Strip a Windows or Azure AD domain without linking automatically."""
    return (value or "").split("\\", 1)[-1].strip()


async def register_pending(session, handover_id, *, employee_code, username, name, actor, client):
    core = HandoverService(session)
    handover = await core.get(handover_id, with_details=True)
    handover.recipient_mode = "pending_user"
    handover.recipient_employee_code = (employee_code or "").strip() or None
    handover.recipient_username = (username or "").strip() or None
    handover.recipient_free_name = (name or "").strip() or None
    await core.record_operation(
        handover_id, Operation.RECIPIENT_CHECK, status=StageStatus.NOT_DONE,
        reason="User not in Snipe-IT yet", detail={"pending_user": True}, actor=actor,
        input_checks=False,
    )
    return await check_pending_user(session, handover_id, actor=actor, client=client)


async def check_pending_user(session, handover_id, *, actor: str, client: SnipeItClient):
    core = HandoverService(session)
    service = SnipeItHandoverService(session)
    handover = await core.get(handover_id, with_details=True)
    now = datetime.now(timezone.utc)
    handover.pending_checked_at = now
    matches = []
    if handover.recipient_username:
        found = await client.find_user(handover.recipient_username)
        if found:
            matches = [found]
    if not matches and handover.recipient_employee_code:
        matches = await client.find_users_by_employee_num(handover.recipient_employee_code)
    if len(matches) > 1:
        await EventRepository(session).add(handover_id=handover.id, actor=actor, type="pending_ambiguous", detail={})
        return await core.get_detail(handover.id)
    if not matches:
        await session.flush()
        return await core.get_detail(handover.id)
    user = matches[0]
    handover.pending_found_at = now
    await EventRepository(session).add(handover_id=handover.id, actor=actor, type="pending_user_found", detail={"user_id": user.id})
    await service.choose_recipient(handover.id, mode="snipeit", user_id=user.id, actor=actor, client=client)
    await service.confirm_recipient_items(handover.id, actor=actor, client=client)
    mismatch = company_conflict(handover.device_company, user.company)
    asset = await client.get_asset_by_serial(handover.device_serial)
    eligible = (asset.status or "").casefold() == config.SNIPEIT_STATUS_READY.casefold() and not mismatch and (asset.assigned_to_id in (None, user.id))
    if eligible:
        await service.checkout(handover.id, actor=actor, client=client)
    return await core.get_detail(handover.id)


async def check_pending_users(session, client: SnipeItClient):
    ids = list((await session.execute(select(Handover.id).where(Handover.recipient_mode == "pending_user", Handover.status.in_(OPEN)))).scalars())
    results = []
    for handover_id in ids:
        try:
            results.append(await check_pending_user(session, handover_id, actor="pending-user-check", client=client))
        except Exception:
            await session.rollback()
            log.exception("pending user check failed case=%s", handover_id)
    return results


async def pending_user_loop(sessionmaker, client_factory, *, hours: float = 24):
    """Sleep first, survive all check errors, and stop cleanly on cancellation."""
    while True:
        await asyncio.sleep(hours * 3600)
        try:
            async with sessionmaker() as session:
                async with client_factory() as client:
                    await check_pending_users(session, client)
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("pending user check loop failed")
