"""Device search and milestone-history API and pages."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import current_user, get_session
from app.repositories.devices import DeviceRepository
from app.services.device_history import DeviceHistoryService

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")


def _service(session):
    return DeviceHistoryService(DeviceRepository(session))


@router.get("/api/devices")
async def devices(
    q: str = Query(default="", max_length=100),
    company: str = Query(default="", max_length=100),
    place: str = Query(default="", pattern="^(lab|user|maintenance|unknown)?$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _service(session).search(q, company, place, order)


@router.get("/api/devices/{serial}/history")
async def history(serial: str, user: dict = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _service(session).history(serial)


@router.get("/devices")
async def devices_page(request: Request, user: dict = Depends(current_user)):
    return templates.TemplateResponse(request=request, name="devices.html", context={"page_title": "Devices", "active_nav": "devices"})


@router.get("/devices/{serial}")
async def device_page(serial: str, request: Request, user: dict = Depends(current_user)):
    return templates.TemplateResponse(request=request, name="device_detail.html", context={"page_title": serial, "active_nav": "devices", "serial": serial})
