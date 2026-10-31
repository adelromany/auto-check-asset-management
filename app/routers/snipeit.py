"""Snipe-IT proxy (token stays server-side).

All HTTP lives in ``app/clients/snipeit.py``. This router only validates the
request, calls one client method and maps typed client errors to HTTP.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.clients.snipeit import (
    ServiceAccountProvider,
    SnipeItAuthError,
    SnipeItClient,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
)
from app.dependencies import current_user

router = APIRouter()


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
