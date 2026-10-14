"""Session-code agent flow.

1. Browser calls GET /api/session/new  → gets a short code like "A7-X3-Q9"
2. Browser polls  GET /api/session/{code}/data every 2 s
3. Agent script POSTs hardware JSON to POST /api/session/{code}/submit
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.dependencies import current_user, get_store
from app.schemas import AgentPayload
from app.services.sessions import SessionStore

router = APIRouter()


@router.get("/api/session/new")
async def new_session(user=Depends(current_user),
                      store: SessionStore = Depends(get_store)):
    """Create a new session code. Called when the page loads."""
    code, ttl = store.create(user)
    return JSONResponse({"code": code, "ttl_seconds": ttl})


@router.get("/api/session/{code}/data")
async def poll_session(code: str,
                       user=Depends(current_user),
                       store: SessionStore = Depends(get_store)):
    """
    Browser polls this endpoint. Returns 202 while waiting, 200 when data arrived.
    """
    session = store.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if session.get("tech", {}).get("email") != user["email"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if session["data"] is None:
        return JSONResponse({"status": "waiting"}, status_code=202)
    return JSONResponse({"status": "ready", "data": session["data"]})


@router.post("/api/session/{code}/submit")
async def submit_session(code: str, payload: AgentPayload,
                         store: SessionStore = Depends(get_store)):
    """
    Agent POSTs hardware info to this endpoint.
    Accepts from any host on the network — no auth needed for the agent
    because the session code is the shared secret (short-lived, random).
    """
    result = store.submit(code, payload.model_dump())
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if result == "already_submitted":
        # Already submitted — idempotent, just return OK
        return JSONResponse({"status": "already_submitted"})

    return JSONResponse({"status": "ok"})
