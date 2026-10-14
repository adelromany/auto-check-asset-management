"""Liveness endpoint."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from app.dependencies import get_store
from app.services.sessions import SessionStore

router = APIRouter()


@router.get("/api/health")
async def health(store: SessionStore = Depends(get_store)):
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat(),
            "sessions_active": store.active_count()}
