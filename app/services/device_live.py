"""One live Snipe-IT device representation shared by cases and lookup screens."""
from __future__ import annotations

from typing import Any

from app.clients.snipeit import SnipeItAsset, SnipeItClient


def _deployable(asset: SnipeItAsset) -> bool:
    if asset.status_deployable is not None:
        return asset.status_deployable
    status = (asset.status or "").strip().casefold()
    return "maintenance" not in status and "undeployable" not in status and "broken" not in status


async def read_device(
    client: SnipeItClient, serial: str, *, exact: bool = False
) -> dict[str, Any]:
    """Read the asset now and enrich its holder only when one is assigned."""
    asset = await (
        client.get_asset_by_exact_serial(serial)
        if exact
        else client.get_asset_by_serial(serial)
    )
    holder = None
    if asset.assigned_to_id is not None:
        user = await client.get_user(asset.assigned_to_id)
        holder = {
            "id": user.id,
            "name": user.name or asset.assigned_to_name or user.username,
            "email": user.email,
            "username": user.username,
            "company": user.company,
        }
    return {
        "asset_id": asset.id,
        "serial": asset.serial or serial,
        "status": asset.status,
        "status_id": asset.status_id,
        "deployable": _deployable(asset),
        "asset_tag": asset.asset_tag,
        "model": asset.model,
        "company": asset.company,
        "assigned_to": holder,
        "found": True,
    }


def store_device_snapshot(handover: Any, device: dict[str, Any]) -> None:
    """Refresh the case fields used by lists without another Snipe-IT call."""
    holder = device.get("assigned_to") or {}
    handover.snipeit_asset_id = device.get("asset_id")
    handover.snipeit_asset_tag = device.get("asset_tag")
    handover.device_company = device.get("company")
    handover.device_model = device.get("model")
    handover.snipeit_status_name = device.get("status")
    handover.device_holder_id = holder.get("id")
    handover.device_holder_name = holder.get("name")
