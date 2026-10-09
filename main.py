"""
Snipe-IT Device Onboarding — Web Application
Phase 2: Local agent support via session codes

Architecture
------------
1. Browser calls GET /api/session/new  → gets a short code like "A7-X3-Q9"
2. Browser polls  GET /api/session/{code}/data every 2 s
3. Tech pastes a one-liner into a terminal on the managed device
4. Agent script POSTs hardware JSON to POST /api/session/{code}/submit
5. Browser poll sees the data → stops polling → renders the hardware section

Sessions are held in memory (dict). They expire after SESSION_TTL_SECONDS.
For a production deployment with multiple workers, replace the in-memory
store with Redis or a small SQLite table — the API surface stays identical.

Run:
    pip install -r requirements.txt
    uvicorn main:app --host 0.0.0.0 --port 8080 --reload
"""

import os
import time
import random
import string
import httpx
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SNIPEIT_URL        = os.getenv("SNIPEIT_URL",   "localhost:8000")
SNIPEIT_TOKEN      = os.getenv("SNIPEIT_TOKEN", "")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL", "600"))   # 10 min default
APP_HOST           = os.getenv("APP_HOST", "localhost:8080")               # e.g. 192.168.1.50:8080

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Snipe-IT Onboarding", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ---------------------------------------------------------------------------
# In-memory session store
# {code: {"created": float, "data": dict|None}}
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}


def _purge_expired():
    """Remove sessions older than TTL. Called on every session-related request."""
    now = time.time()
    expired = [k for k, v in _sessions.items() if now - v["created"] > SESSION_TTL_SECONDS]
    for k in expired:
        del _sessions[k]


def _make_code() -> str:
    """Generate a human-readable 6-character session code, e.g. A7-X3-Q9."""
    chars = string.ascii_uppercase + string.digits
    raw = "".join(random.choices(chars, k=6))
    return f"{raw[0:2]}-{raw[2:4]}-{raw[4:6]}"


# ---------------------------------------------------------------------------
# Pydantic model for agent POST body
# ---------------------------------------------------------------------------

class AgentPayload(BaseModel):
    hostname:     Optional[str] = None
    username:     Optional[str] = None
    serial:       Optional[str] = None
    manufacturer: Optional[str] = None
    model:        Optional[str] = None
    cpu:          Optional[str] = None
    cpu_cores:    Optional[int] = None
    ram_gb:       Optional[float] = None
    disks:        Optional[list] = None   # [{name, size_gb, type}]
    os_name:      Optional[str] = None
    os_version:   Optional[str] = None
    os_arch:      Optional[str] = None
    ip_addresses:  Optional[list] = None  # [{iface, ip}]
    agent_os:     Optional[str] = None    # "windows" | "macos" | "linux"
    collected_at: Optional[str] = None
    # ── Phase 3 additions ──────────────────────────────────────────────
    software_checks:     Optional[list] = None
    # [{id, name, installed: bool, version: str|None, method: str}]
    windows_activation:  Optional[dict] = None
    # {status: str, status_code: int, product_name: str, partial_key: str}


# ---------------------------------------------------------------------------
# Routes — pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    host = APP_HOST or f"http://{request.headers.get('host', 'localhost:8080')}"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_host": host,
        },
    )



# ---------------------------------------------------------------------------
# Routes — session API
# ---------------------------------------------------------------------------

@app.get("/api/session/new")
async def new_session():
    """Create a new session code. Called when the page loads."""
    _purge_expired()
    code = _make_code()
    # Extremely unlikely collision, but guard anyway
    while code in _sessions:
        code = _make_code()
    _sessions[code] = {"created": time.time(), "data": None}
    ttl = SESSION_TTL_SECONDS
    return JSONResponse({"code": code, "ttl_seconds": ttl})


@app.get("/api/session/{code}/data")
async def poll_session(code: str):
    """
    Browser polls this endpoint. Returns 202 while waiting, 200 when data arrived.
    """
    _purge_expired()
    session = _sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if session["data"] is None:
        return JSONResponse({"status": "waiting"}, status_code=202)
    return JSONResponse({"status": "ready", "data": session["data"]})


@app.post("/api/session/{code}/submit")
async def submit_session(code: str, payload: AgentPayload):
    """
    Agent POSTs hardware info to this endpoint.
    Accepts from any host on the network — no auth needed for the agent
    because the session code is the shared secret (short-lived, random).
    """
    _purge_expired()
    session = _sessions.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if session["data"] is not None:
        # Already submitted — idempotent, just return OK
        return JSONResponse({"status": "already_submitted"})

    session["data"] = payload.model_dump()
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Routes — Snipe-IT proxy (token stays server-side)
# ---------------------------------------------------------------------------

@app.get("/api/snipeit/device")
async def lookup_device(serial: str):
    """Look up a device in Snipe-IT by serial number."""
    if not serial or len(serial.strip()) < 3:
        raise HTTPException(status_code=400, detail="Serial number too short.")
    if not SNIPEIT_TOKEN:
        raise HTTPException(status_code=503, detail="Snipe-IT token not configured.")

    headers = {
        "Authorization": f"Bearer {SNIPEIT_TOKEN}",
        "Accept":        "application/json",
        "Content-Type":  "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{SNIPEIT_URL}/api/v1/hardware",
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


@app.get("/api/snipeit/health")
async def snipeit_health():
    """Check whether the configured Snipe-IT API is reachable with the current token."""
    if not SNIPEIT_TOKEN:
        return JSONResponse({"connected": False, "reason": "token_not_configured"})

    headers = {
        "Authorization": f"Bearer {SNIPEIT_TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SNIPEIT_URL}/api/v1/hardware",
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


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(), "sessions_active": len(_sessions)}
