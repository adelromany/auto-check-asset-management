"""One filter builder for every case list (repository layer).

The server-rendered `/cases` page, the dashboard page and
``GET /api/handovers`` all call :func:`build_case_filters`, so a filter can
never drift between them.

Search is a case-insensitive substring over the case and, when the case is
maintenance, its typed maintenance fields. Wildcard characters in user input
are escaped and every value is bound; nothing is interpolated into SQL.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, func, or_, select

from app.db.models.handover import Handover
from app.db.models.maintenance import MaintenanceDestination, MaintenanceInfo
from app.domain.stages import HandoverStatus

SEARCH_MIN_LENGTH = 2
SEARCH_MAX_LENGTH = 100


def escape_like(value: str) -> str:
    """Escape ``\``, ``%`` and ``_`` so user input is a literal substring."""
    return (
        value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def search_pattern(query: str) -> str:
    return f"%{escape_like(query.strip().casefold())}%"


def _contains(column, pattern: str):
    return func.lower(column).like(pattern, escape="\\")


def _search_condition(query: str):
    """Literal, case-insensitive substring across every searchable field."""
    pattern = search_pattern(query)
    maintenance_match = (
        select(MaintenanceInfo.handover_id)
        .outerjoin(
            MaintenanceDestination,
            MaintenanceDestination.id == MaintenanceInfo.destination_id,
        )
        .where(
            or_(
                _contains(MaintenanceInfo.reported_issue, pattern),
                _contains(MaintenanceInfo.reference, pattern),
                _contains(MaintenanceInfo.sent_by, pattern),
                _contains(MaintenanceDestination.name, pattern),
            )
        )
        .scalar_subquery()
    )
    return or_(
        _contains(Handover.device_serial, pattern),
        _contains(Handover.snipeit_asset_tag, pattern),
        _contains(Handover.ticket_ref, pattern),
        _contains(Handover.engineer_email, pattern),
        _contains(Handover.engineer_name, pattern),
        _contains(Handover.recipient_reported_username, pattern),
        _contains(Handover.recipient_snipeit_username, pattern),
        _contains(Handover.recipient_snipeit_name, pattern),
        _contains(Handover.recipient_snipeit_email, pattern),
        Handover.id.in_(maintenance_match),
    )


def _status_condition(status: str | None, stall_cutoff: datetime | None):
    """Resolve the stored status plus the age-only ``stalled`` overlay."""
    stale = None
    if stall_cutoff is not None:
        stale = and_(
            Handover.status.in_(
                [HandoverStatus.DRAFT.value, HandoverStatus.IN_PROGRESS.value]
            ),
            Handover.updated_at < stall_cutoff,
        )
    if status == HandoverStatus.STALLED.value and stale is not None:
        return stale
    if status in (
        HandoverStatus.DRAFT.value,
        HandoverStatus.IN_PROGRESS.value,
    ) and stale is not None:
        return and_(Handover.status == status, Handover.updated_at >= stall_cutoff)
    if status is not None:
        return Handover.status == status
    return None


def build_case_filters(
    *,
    status: str | None = None,
    engineer: str | None = None,
    kind: str | None = None,
    q: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    stall_cutoff: datetime | None = None,
) -> list:
    """Every filter for a case list, in one place."""
    filters = []
    status_filter = _status_condition(status, stall_cutoff)
    if status_filter is not None:
        filters.append(status_filter)
    if engineer:
        filters.append(Handover.engineer_email == engineer)
    if kind:
        filters.append(Handover.kind == kind)
    if created_from is not None:
        filters.append(Handover.created_at >= created_from)
    if created_to is not None:
        filters.append(Handover.created_at <= created_to)
    cleaned_query = (q or "").strip()
    if cleaned_query:
        filters.append(_search_condition(cleaned_query))
    return filters
