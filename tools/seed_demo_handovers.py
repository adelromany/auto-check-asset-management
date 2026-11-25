"""Seed clearly marked demo handovers so the dashboard can be judged.

Rows live only in the portal database (never Snipe-IT), use serials with the
``DEMO-`` prefix, and can be removed again with ``--remove``.

    python tools/seed_demo_handovers.py --count 60
    python tools/seed_demo_handovers.py --remove
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import config  # noqa: E402
from app.db.models.handover import Event, Handover, HandoverStage  # noqa: E402
from app.domain.catalog import HANDOVER_OPERATIONS  # noqa: E402
from app.domain.stages import HandoverStatus, StageStatus  # noqa: E402

DEMO_PREFIX = "DEMO-"
COMPANIES = ("B.tech", "Nexta", "Mylo")
MODELS = ("Latitude 5440", "Latitude 5540", "ThinkPad T14", "EliteBook 840")
ENGINEERS = (
    ("Demo Engineer 1", "demo.engineer1@example.com"),
    ("Demo Engineer 2", "demo.engineer2@example.com"),
    ("Demo Engineer 3", "demo.engineer3@example.com"),
)


def _refuse_production() -> bool:
    environment = os.getenv("APP_ENV", "development").strip().lower()
    if environment == "production":
        print("Refused: APP_ENV=production. Demo tools never touch production.")
        return True
    return False


async def _demo_ids(connection) -> list:
    result = await connection.execute(
        text("SELECT id FROM handovers WHERE device_serial LIKE :prefix"),
        {"prefix": DEMO_PREFIX + "%"},
    )
    return [row[0] for row in result.all()]


async def remove_demo(database_url: str | None = None) -> int:
    url = database_url or config.DATABASE_URL
    engine = create_async_engine(url)
    removed = 0
    try:
        async with engine.begin() as connection:
            ids = await _demo_ids(connection)
            if ids:
                placeholders = ", ".join(
                    f":id{index}" for index in range(len(ids))
                )
                params = {
                    f"id{index}": value for index, value in enumerate(ids)
                }
                for table in (
                    "handover_stages",
                    "events",
                    "documents",
                    "agent_reports",
                    "maintenance_info",
                ):
                    await connection.execute(
                        text(
                            f'DELETE FROM "{table}" '
                            f"WHERE handover_id IN ({placeholders})"
                        ),
                        params,
                    )
                await connection.execute(
                    text(
                        f'DELETE FROM "handovers" '
                        f"WHERE id IN ({placeholders})"
                    ),
                    params,
                )
                removed = len(ids)
    finally:
        await engine.dispose()
    return removed


def _stage_rows(
    handover_id: uuid.UUID, *, outcome: str, index: int
) -> list[HandoverStage]:
    passed_count = 9 if outcome == "complete" else 3 if outcome == "ready" else 3 + (index % 4)
    rows: list[HandoverStage] = []
    for position, operation in enumerate(HANDOVER_OPERATIONS):
        status = StageStatus.PENDING.value
        reason = None
        if position < passed_count:
            status = StageStatus.PASSED.value
        elif outcome == "ready" and operation.value == "recipient_check":
            status = StageStatus.NOT_DONE.value
            reason = "No recipient yet"
        elif outcome != "complete" and index % 6 == 5 and operation.value == "software_check":
            status = StageStatus.FAILED.value
            reason = "Required software missing"
        elif outcome != "complete" and index % 11 == 4 and operation.value == "document_scanned":
            status = StageStatus.NOT_DONE.value
            reason = "Signed paper not scanned"
        rows.append(
            HandoverStage(
                handover_id=handover_id,
                stage=operation.value,
                status=status,
                reason=reason,
            )
        )
    return rows


async def seed_demo(
    count: int = 60, database_url: str | None = None
) -> int:
    url = database_url or config.DATABASE_URL
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    created = 0
    try:
        async with factory() as session:
            for index in range(count):
                outcome = (
                    "complete"
                    if index % 5 in (0, 1)
                    else "ready"
                    if index % 5 == 2
                    else "open"
                )
                status = {
                    "complete": HandoverStatus.COMPLETED.value,
                    "ready": HandoverStatus.READY.value,
                    "open": HandoverStatus.IN_PROGRESS.value,
                }[outcome]
                company = COMPANIES[index % len(COMPANIES)]
                model = MODELS[index % len(MODELS)]
                engineer = ENGINEERS[index % len(ENGINEERS)]
                case_start = now - timedelta(hours=(index * 11) % (30 * 24))
                closed_at = (
                    case_start + timedelta(hours=3 + (index % 30))
                    if outcome == "complete"
                    else None
                )
                warning = index % 9 == 3
                waiting = outcome == "open" and index % 7 == 2
                stalled = (
                    outcome == "open"
                    and index % 4 == 3
                )
                handover_id = uuid.uuid4()
                handover = Handover(
                    id=handover_id,
                    kind="handover",
                    status=status,
                    engineer_email=engineer[1],
                    engineer_name=engineer[0],
                    device_serial=f"{DEMO_PREFIX}{index + 1:04d}",
                    snipeit_asset_id=9000 + index,
                    device_company=company,
                    device_model=model,
                    device_category="Laptop",
                    snipeit_status_name=(
                        "Ready to deploy"
                        if outcome in ("complete", "ready")
                        else "Deployed"
                    ),
                    recipient_mode=(
                        "none"
                        if outcome == "ready"
                        else "pending_user"
                        if waiting
                        else "snipeit"
                    ),
                    recipient_snipeit_id=None if outcome == "ready" else 5000 + index,
                    recipient_snipeit_username=None if outcome == "ready" else f"demo.user{index}",
                    recipient_snipeit_name=None if outcome == "ready" else f"Demo User {index}",
                    recipient_company=(
                        COMPANIES[(index + 1) % len(COMPANIES)]
                        if warning
                        else company
                    )
                    if outcome != "ready"
                    else None,
                    created_at=case_start,
                    updated_at=(
                        now - timedelta(hours=36 + index)
                        if stalled
                        else closed_at or case_start + timedelta(hours=1)
                    ),
                    closed_at=closed_at,
                )
                session.add(handover)
                session.add_all(
                    _stage_rows(handover_id, outcome=outcome, index=index)
                )
                events = [
                    Event(
                        handover_id=handover_id,
                        at=case_start,
                        actor=engineer[1],
                        type="handover_created",
                        detail={},
                    )
                ]
                if outcome != "ready":
                    events.append(
                        Event(
                            handover_id=handover_id,
                            at=case_start + timedelta(minutes=40),
                            actor=engineer[1],
                            type="recipient_changed",
                            detail={
                                "old_name": "",
                                "new_name": f"Demo User {index}",
                            },
                        )
                    )
                if warning:
                    events.append(
                        Event(
                            handover_id=handover_id,
                            at=case_start + timedelta(hours=1),
                            actor=engineer[1],
                            type="company_mismatch_warning",
                            detail={
                                "device_company": company,
                                "recipient_company": COMPANIES[
                                    (index + 1) % len(COMPANIES)
                                ],
                                "engineer": engineer[1],
                            },
                        )
                    )
                if waiting:
                    events.append(
                        Event(
                            handover_id=handover_id,
                            at=case_start + timedelta(hours=2),
                            actor=engineer[1],
                            type="pending_user_found",
                            detail={"username": f"demo.user{index}"},
                        )
                    )
                if outcome == "complete":
                    events.append(
                        Event(
                            handover_id=handover_id,
                            at=closed_at,
                            actor=engineer[1],
                            type="checkout_attempt",
                            detail={"outcome": "passed"},
                        )
                    )
                session.add_all(events)
                created += 1
            await session.commit()
    finally:
        await engine.dispose()
    return created


async def _run(args: argparse.Namespace) -> int:
    if _refuse_production():
        return 2
    if args.remove:
        removed = await remove_demo()
        print(f"Removed {removed} demo handover(s).")
        return 0
    created = await seed_demo(count=args.count)
    print(f"Seeded {created} demo handover(s).")
    print("Remove with: python tools/seed_demo_handovers.py --remove")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    if args.count < 1:
        parser.error("--count must be at least 1")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
