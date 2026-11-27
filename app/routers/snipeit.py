"""Snipe-IT proxy (token stays server-side).

All HTTP lives in ``app/clients/snipeit.py``. This router only validates the
request, calls one client method and maps typed client errors to HTTP.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import (
    ServiceAccountProvider,
    SnipeItAuthError,
    SnipeItClient,
    SnipeItError,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
)
from app.dependencies import current_user, get_session, get_snipeit_client
from app.domain.errors import HandoverError
from app.dto.handover import SnipeItUserSearchResult
from app.routers.http_errors import handover_http_error, snipeit_http_error
from app.services.handovers import HandoverService

router = APIRouter()


@router.get("/api/snipeit/device-lookup")
async def live_device_lookup(
    serial: str = Query(min_length=3, max_length=100),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
):
    """Shared live card for the new-case drawer and device screens."""
    from app.services.device_live import read_device

    try:
        device = await read_device(client, serial)
        candidates = await client.search_assets(serial)
        active = await HandoverService(session).find_active_by_serial(serial)
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return {
        **device,
        "multiple": len(candidates) > 1,
        "candidates": [
            {"asset_id": item.id, "asset_tag": item.asset_tag, "serial": item.serial, "model": item.model}
            for item in candidates
        ] if len(candidates) > 1 else [],
        "open_case": ({"id": str(active.id), "url": (f"/maintenance/{active.id}" if active.kind == "maintenance" else f"/handovers/{active.id}")} if active else None),
    }


def _client(user: dict) -> SnipeItClient:
    return SnipeItClient(
        config.SNIPEIT_URL,
        ServiceAccountProvider(config.SNIPEIT_TOKEN),
        timeout=config.SNIPEIT_TIMEOUT_SECONDS,
        engineer_email=(user or {}).get("email") or "",
    )


@router.get("/api/snipeit/device")
async def lookup_device(serial: str, user=Depends(current_user)):
    """Look up a device in Snipe-IT by serial number."""
    if not serial or len(serial.strip()) < 3:
        raise HTTPException(status_code=400, detail="Serial number too short.")
    if not config.SNIPEIT_TOKEN:
        raise HTTPException(status_code=503, detail="Snipe-IT token not configured.")

    client = _client(user)
    try:
        asset = await client.get_asset_by_serial(serial)
    except SnipeItUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SnipeItAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except SnipeItNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SnipeItRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        await client.aclose()

    return JSONResponse({
        "found":         True,
        "asset_tag":     asset.asset_tag,
        "name":          asset.name,
        "serial":        asset.serial,
        "status":        asset.status,
        "model":         asset.model,
        "category":      asset.category,
        "manufacturer":  asset.manufacturer,
        "assigned_to":   asset.assigned_to_name,
        "location":      asset.location,
        "last_checkout": asset.last_checkout,
        "purchase_date": asset.purchase_date,
        "warranty_months": asset.warranty_months,
        "notes":         asset.notes,
    })


@router.get("/api/snipeit/users", response_model=list[SnipeItUserSearchResult])
async def search_snipeit_users(
    q: str = Query(min_length=2, max_length=200),
    handover_id: uuid.UUID = Query(),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
    client: SnipeItClient = Depends(get_snipeit_client),
) -> list[SnipeItUserSearchResult]:
    """Search Snipe-IT users and show whether each matches the device company."""
    service = HandoverService(session)
    try:
        users = await service.search_snipeit_users(
            handover_id, q, client=client
        )
    except HandoverError as exc:
        raise handover_http_error(exc) from exc
    except SnipeItError as exc:
        raise snipeit_http_error(exc) from exc
    return [SnipeItUserSearchResult.model_validate(user) for user in users]


@router.get("/api/snipeit/status-labels")
async def status_labels(user=Depends(current_user)):
    """Every Snipe-IT status label as {id, name}."""
    if not config.SNIPEIT_TOKEN:
        raise HTTPException(status_code=503, detail="Snipe-IT token not configured.")

    client = _client(user)
    try:
        labels = await client.list_status_labels()
    except SnipeItUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SnipeItAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except SnipeItRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        await client.aclose()

    return [{"id": label_id, "name": name} for label_id, name in labels]


@router.get("/api/snipeit/health")
async def snipeit_health(user=Depends(current_user)):
    """Check whether the configured Snipe-IT API is reachable with the token."""
    if not config.SNIPEIT_URL.strip() or not config.SNIPEIT_TOKEN.strip():
        if not config.SNIPEIT_TOKEN.strip():
            # Preserve the established response body for the missing-token
            # case; the UI maps this stable reason to a readable message.
            return JSONResponse(
                {"connected": False, "reason": "token_not_configured"}
            )
        return JSONResponse({
            "connected": False,
            "reason": "not_configured",
            "message": "Snipe-IT is not configured.",
        })

    client = _client(user)
    try:
        await client.whoami()
    except SnipeItUnavailable:
        return JSONResponse({"connected": False, "reason": "unreachable"})
    except SnipeItAuthError as exc:
        return JSONResponse(
            {
                "connected": False,
                "reason": "api_error",
                "status_code": exc.status_code,
            }
        )
    except SnipeItNotFound:
        return JSONResponse(
            {"connected": False, "reason": "api_error", "status_code": 404}
        )
    except SnipeItRejected as exc:
        return JSONResponse(
            {
                "connected": False,
                "reason": "api_error",
                "status_code": exc.status_code,
            }
        )
    finally:
        await client.aclose()

    return JSONResponse(
        {"connected": True, "reason": None, "status_code": 200}
    )
