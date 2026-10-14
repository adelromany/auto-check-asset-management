"""Snipe-IT proxy (token stays server-side)."""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.dependencies import current_user

router = APIRouter()


@router.get("/api/snipeit/device")
async def lookup_device(serial: str, user=Depends(current_user)):
    """Look up a device in Snipe-IT by serial number."""
    if not serial or len(serial.strip()) < 3:
        raise HTTPException(status_code=400, detail="Serial number too short.")
    if not config.SNIPEIT_TOKEN:
        raise HTTPException(status_code=503, detail="Snipe-IT token not configured.")

    headers = {
        "Authorization": f"Bearer {config.SNIPEIT_TOKEN}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{config.SNIPEIT_URL}/api/v1/hardware",
                headers=headers,
                params={"search": serial.strip(), "limit": 10},
            )
        resp.raise_for_status()
        data = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Snipe-IT: {exc}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=f"Snipe-IT error: {exc.response.text}",
        )

    rows = data.get("rows", [])
    exact = next((r for r in rows if r.get("serial", "").strip() == serial.strip()), None)
    asset = exact or (rows[0] if rows else None)

    if not asset:
        raise HTTPException(status_code=404, detail=f"No device found for serial: {serial}")

    return JSONResponse({
        "found":         True,
        "asset_tag":     asset.get("asset_tag"),
        "name":          asset.get("name"),
        "serial":        asset.get("serial"),
        "status":        asset.get("status_label", {}).get("name")      if asset.get("status_label") else None,
        "model":         asset.get("model", {}).get("name")              if asset.get("model")        else None,
        "category":      asset.get("category", {}).get("name")           if asset.get("category")     else None,
        "manufacturer":  asset.get("manufacturer", {}).get("name")       if asset.get("manufacturer") else None,
        "assigned_to":   asset.get("assigned_to", {}).get("name")        if asset.get("assigned_to")  else None,
        "location":      asset.get("location", {}).get("name")           if asset.get("location")     else None,
        "last_checkout": asset.get("last_checkout"),
        "purchase_date": asset.get("purchase_date", {}).get("formatted") if asset.get("purchase_date") else None,
        "warranty_months": asset.get("warranty_months"),
        "notes":         asset.get("notes"),
    })


@router.get("/api/snipeit/health")
async def snipeit_health():
    """Check whether the configured Snipe-IT API is reachable with the current token."""
    if not config.SNIPEIT_TOKEN:
        return JSONResponse({"connected": False, "reason": "token_not_configured"})

    headers = {
        "Authorization": f"Bearer {config.SNIPEIT_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{config.SNIPEIT_URL}/api/v1/hardware",
                headers=headers,
                params={"limit": 1},
            )
    except httpx.RequestError:
        return JSONResponse({"connected": False, "reason": "unreachable"})

    return JSONResponse({
        "connected": resp.is_success,
        "reason": None if resp.is_success else "api_error",
        "status_code": resp.status_code,
    })
