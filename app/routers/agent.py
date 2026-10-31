"""Session-code agent flow.

1. Browser calls GET /api/session/new  → gets a short code like "A7-X3-Q9"
2. Browser polls  GET /api/session/{code}/data every 2 s
3. Agent script POSTs hardware JSON to POST /api/session/{code}/submit

A session may optionally be linked to a handover. Without that link the flow
is byte-for-byte the pre-Phase-2 behavior and never touches the database.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import current_user, get_session, get_store
from app.domain.errors import HandoverError
from app.schemas import AgentPayload
from app.services.handovers import HandoverService
from app.services.sessions import SessionStore

router = APIRouter()


@router.get("/api/session/new")
async def new_session(
    handover_id: uuid.UUID | None = Query(default=None),
    user=Depends(current_user),
    store: SessionStore = Depends(get_store),
):
    """Create a new session code. Called when the page loads."""
    code, ttl = store.create(
        user, handover_id=str(handover_id) if handover_id else None
    )
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
                         store: SessionStore = Depends(get_store),
                         session: AsyncSession = Depends(get_session)):
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

    await _record_handover_report(store.get(code), payload, session)
    return JSONResponse({"status": "ok"})


async def _record_handover_report(
    session_record: dict | None,
    payload: AgentPayload,
    session: AsyncSession,
) -> None:
    """Persist the report when the session is linked to a handover.

    Bookkeeping must never break the agent flow: an unknown, cancelled or
    completed handover simply leaves the submission untouched.
    """
    if not session_record or not session_record.get("handover_id"):
        return
    try:
        handover_id = uuid.UUID(str(session_record["handover_id"]))
    except (TypeError, ValueError):
        return

    actor = (session_record.get("tech") or {}).get("email") or "agent"
    try:
        await HandoverService(session).record_agent_report(
            handover_id, payload.model_dump(), actor=actor
        )
    except HandoverError:
        # The agent's contract is unchanged; the engineer sees the handover
        # state in the portal.
        return
