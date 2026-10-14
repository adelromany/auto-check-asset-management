"""Read-only clipboard diagnostics (local troubleshooting tool).

Enabled only with ENABLE_DIAG=true. Collects no personal data beyond the
browser user-agent string, which the engineer submits voluntarily via
"Copy report" / the optional report endpoint.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app import config

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/diag/clipboard", response_class=HTMLResponse)
async def clipboard_diag(request: Request):
    if not config.ENABLE_DIAG:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return templates.TemplateResponse(
        request=request,
        name="diag_clipboard.html",
        context={},
    )


@router.post("/diag/clipboard/report")
async def clipboard_diag_report(request: Request):
    """Accept a diagnostics payload and log it server-side. No storage."""
    if not config.ENABLE_DIAG:
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON"}, status_code=400)
    allowed = {"isSecureContext", "protocol", "host", "clipboardType",
               "writeTextType", "permission", "methodA", "methodB",
               "userAgent", "platform"}
    logged = {k: payload.get(k) for k in allowed if k in payload}
    print(f"[diag/clipboard] {logged}")
    return JSONResponse({"logged": True})
