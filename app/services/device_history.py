"""Milestone cards and list summaries for a device's whole portal history."""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

from app.domain.company_rules import company_conflict
from app.domain.handover_rules import Outcome, case_outcome, missing_parts
from app.services.handovers import stage_states


def _at(value: date | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.combine(value, time.max)
    return result.replace(tzinfo=None)


def _fact(label: str, value: Any, kind: str = "plain") -> dict:
    return {"label": label, "value": str(value or "—"), "kind": kind}


def _reason(case) -> str:
    info = case.maintenance
    return (info and (info.diagnosis_category or info.reason_text)) or "Maintenance"


def _vendor(case) -> str:
    info = case.maintenance
    return (info and info.destination and info.destination.name) or "Vendor"


def _days(info, until: date | None = None) -> int:
    if not info or not info.received_date:
        return 0
    return max(0, ((until or date.today()) - info.received_date).days)


def build_cards(cases, *, today: date | None = None) -> list[dict]:
    """Build milestone cards from loaded cases; cancelled cases never appear."""
    today = today or date.today()
    cards = []
    for case in cases:
        if case.status == "cancelled":
            continue
        url = f"/maintenance/{case.id}" if case.kind == "maintenance" else f"/handovers/{case.id}"
        if case.kind == "handover":
            outcome = case_outcome(stage_states(case), recipient_mode=case.recipient_mode)
            if outcome is Outcome.COMPLETE:
                cards.append({"date": getattr(case, "closed_at", None) or case.updated_at, "tag": "Handover", "headline": f"Handed over to {case.recipient_snipeit_name or case.recipient_free_name or 'recipient'}", "facts": [_fact("STATUS", "Complete", "chip-ok"), _fact("USER", case.recipient_snipeit_name or case.recipient_free_name), _fact("COMPANY", (case.recipient_company or "—") + (" !" if company_conflict(case.device_company, case.recipient_company) else ""), "chip-warn" if company_conflict(case.device_company, case.recipient_company) else "plain"), _fact("ENGINEER", case.engineer_name)], "case_url": url})
            elif outcome is Outcome.READY:
                cards.append({"date": getattr(case, "closed_at", None) or case.updated_at, "tag": "Handover", "headline": "Prepared as Ready lab", "facts": [_fact("STATUS", "Ready lab", "chip-ok"), _fact("ENGINEER", case.engineer_name)], "case_url": url})
            else:
                missing = missing_parts(stage_states(case), case.recipient_mode)[:3]
                cards.append({"date": case.created_at, "tag": "Handover", "headline": "Handover in progress", "facts": [_fact("STATUS", "Not complete", "chip-warn"), _fact("USER", case.recipient_snipeit_name or "Waiting for user"), _fact("MISSING", ", ".join(missing) or "None")], "case_url": url})
            continue
        info = case.maintenance
        if not info:
            continue
        common = [_fact("COMPANY", case.device_company)]
        if info.received_date:
            cards.append({"date": info.received_date, "tag": "Maintenance", "headline": f"Received for maintenance - {_reason(case)}", "facts": [_fact("STATUS", "With IT", "chip-info"), *common, _fact("FROM", case.recipient_snipeit_name)], "case_url": url})
        if info.sent_date:
            cards.append({"date": info.sent_date, "tag": "Maintenance", "headline": f"Dispatched to {_vendor(case)} - {_reason(case)}", "facts": [_fact("STATUS", "In maintenance", "chip-warn"), _fact("VENDOR", _vendor(case)), *common, _fact("DAYS", _days(info, info.sent_date))], "case_url": url})
        if info.returned_date:
            cards.append({"date": info.returned_date, "tag": "Maintenance", "headline": f"Returned from {_vendor(case)} - {_reason(case)}", "facts": [_fact("STATUS", "Maintenance completed", "chip-ok"), _fact("VENDOR", _vendor(case)), *common, _fact("DAYS", _days(info, info.returned_date))], "case_url": url})
    priority = {"Returned": 3, "Dispatched": 2, "Received": 1}
    return sorted(cards, key=lambda card: (_at(card["date"]), priority.get(card["headline"].split()[0], 0)), reverse=True)


PLACE_KINDS = ("lab", "user", "maintenance", "unknown")


def device_place(case) -> tuple[str, str]:
    """(label, kind) for where a device is now, judged from its latest case.

    kind is one of PLACE_KINDS: lab (with IT / ready), user (with a holder),
    maintenance (repair case, with IT or at a vendor) or unknown (the latest
    case was cancelled and no holder is known, so nothing says where it is).
    """
    if case.kind == "maintenance":
        label = f"At vendor {_vendor(case)}" if case.maintenance_state == "at_vendor" else "With IT"
        return label, "maintenance"
    if case.device_holder_name:
        return f"With {case.device_holder_name}", "user"
    if case.status == "cancelled":
        return "Unknown", "unknown"
    if case_outcome(stage_states(case), recipient_mode=case.recipient_mode) is Outcome.READY:
        return "Ready lab", "lab"
    return "With IT", "lab"


class DeviceHistoryService:
    def __init__(self, repository):
        self._repository = repository

    async def history(self, serial: str) -> dict:
        cases = await self._repository.cases(serial)
        cards = build_cards(cases)
        complete = sum(case.kind == "handover" and case_outcome(stage_states(case), recipient_mode=case.recipient_mode) is Outcome.COMPLETE for case in cases if case.status != "cancelled")
        maintenance = [case for case in cases if case.kind == "maintenance" and case.status != "cancelled"]
        total_days = sum(_days(case.maintenance, case.maintenance.returned_date) for case in maintenance)
        active_cases = [case for case in cases if case.status != "cancelled"]
        latest = active_cases[0] if active_cases else None
        now = "Ready lab"
        if latest:
            if latest.kind == "maintenance" and latest.maintenance_state == "at_vendor":
                now = f"At vendor {_vendor(latest)}"
            elif latest.kind == "maintenance":
                now = "With IT"
            elif latest.device_holder_name:
                now = f"With {latest.device_holder_name}"
            elif case_outcome(stage_states(latest), recipient_mode=latest.recipient_mode) is not Outcome.READY:
                now = "With IT"
        return {"serial": serial, "device": {"model": latest.device_model if latest else None, "company": latest.device_company if latest else None}, "cards": cards, "summary": {"now": now, "handovers": complete, "maintenance_count": len(maintenance), "maintenance_days": total_days, "last_activity": cases[0].updated_at if cases else None}}

    async def search(
        self, q: str = "", company: str = "", place: str = "", order: str = "desc"
    ) -> dict:
        """Latest-known state of every device, filtered and sorted for the list page.

        ``counts`` and ``companies`` ignore the place filter / company filter
        respectively so the filter chips and the select keep showing what exists.
        """
        cases = await self._repository.cases()
        latest = {}
        for case in cases:
            key = case.device_serial.casefold()
            if key not in latest or latest[key].status == "cancelled":
                latest[key] = case
        needle = q.strip().casefold()
        everything = []
        for case in latest.values():
            label, kind = device_place(case)
            everything.append({
                "serial": case.device_serial, "asset_tag": case.snipeit_asset_tag,
                "model": case.device_model, "company": case.device_company,
                "place": label, "place_kind": kind, "holder": case.device_holder_name,
                "last_activity": case.updated_at, "url": f"/devices/{case.device_serial}",
            })
        companies = sorted({row["company"] for row in everything if row["company"]}, key=str.casefold)
        searched = [
            row for row in everything
            if needle in " ".join(str(row[key] or "") for key in ("serial", "asset_tag", "model")).casefold()
        ]
        in_company = [row for row in searched if not company or row["company"] == company]
        counts = {kind: sum(row["place_kind"] == kind for row in in_company) for kind in PLACE_KINDS}
        rows = [row for row in in_company if not place or row["place_kind"] == place]
        rows.sort(key=lambda row: _at(row["last_activity"]), reverse=order != "asc")
        return {"items": rows, "total": len(rows), "companies": companies, "counts": counts}
