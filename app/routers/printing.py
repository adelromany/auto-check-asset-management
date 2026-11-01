"""Print Laptop Form — session inventory → DOCX → PDF → Windows printer.

Endpoints:
  GET  /api/print/printers           → queues installed on this server
  GET  /api/print/jobs?printer=NAME  → current spooler jobs of one queue
  POST /api/session/{code}/print     → fill, convert, submit (same ownership
                                       rules as the session data endpoints)

Heavy work runs in a worker thread (subprocesses); failures surface as typed
HTTP errors with actionable messages — no server paths or commands leak into
the GUI, so responses only carry queue names, document names and statuses.
"""

import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from app import config
from app.clients.snipeit import SnipeItAsset, SnipeItClient, SnipeItError
from app.dependencies import current_user, get_snipeit_client, get_store
from app.schemas import PrintRequest
from app.services import laptop_form, printing
from app.services.sessions import SessionStore

router = APIRouter()


@router.get("/api/print/printers")
async def list_printers(user=Depends(current_user)):
    """Enumerate the Windows print queues installed on this server."""
    try:
        printers = printing.enumerate_printers()
    except printing.PrintingError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    printer_names = sorted(p["name"] for p in printers if p.get("name"))
    return JSONResponse({
        "printers": printers,
        "printer_names": printer_names,
        "configured": config.PRINT_PRINTER,
        "selector_enabled": config.PRINT_ALLOW_PRINTER_SELECTOR,
        "template_found": os.path.isfile(config.FORM_TEMPLATE_PATH),
    })


@router.get("/api/print/jobs")
async def print_jobs(printer: str, user=Depends(current_user)):
    """Current spooler jobs of one queue — lets the GUI distinguish an
    accepted job from a physically printed document."""
    printer = (printer or "").strip()
    if not printer:
        raise HTTPException(status_code=400, detail="Missing ?printer= name.")
    try:
        jobs = printing.query_jobs(printer)
    except printing.PrintingError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return JSONResponse({"printer": printer, "jobs": jobs})


@router.post("/api/session/{code}/print")
async def print_laptop_form(code: str, body: PrintRequest | None = None,
                            user=Depends(current_user),
                            store: SessionStore = Depends(get_store),
                            client: SnipeItClient = Depends(get_snipeit_client)):
    """Fill Laptop Form with this session's latest inventory and print it.

    Same session-ownership rules as GET /api/session/{code}/data. The heavy
    work (docx fill, pdf conversion, spool submission) runs off the event loop.
    """
    session = store.get(code)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    if session.get("tech", {}).get("email") != user["email"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    data = session["data"]
    if not data:
        raise HTTPException(
            status_code=409,
            detail="No inventory data for this session yet — run the agent "
                   "command first, then print.")

    requested = (body.printer if body else None) or ""
    requested = requested.strip()

    # ── printer selection (never the interactive user's default printer) ──────
    if requested and not config.PRINT_ALLOW_PRINTER_SELECTOR:
        raise HTTPException(
            status_code=403,
            detail="Printer selection is disabled on this server. The "
                   "administrator-configured queue will be used.")
    if config.PRINT_ALLOW_PRINTER_SELECTOR and requested:
        try:
            exists = printing.printer_exists(requested)
        except printing.PrintingError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        if not exists:
            raise HTTPException(
                status_code=503,
                detail=f"Printer '{requested}' is not installed on this server.")
        printer = requested
    else:
        printer = config.PRINT_PRINTER.strip()
        if not printer:
            raise HTTPException(
                status_code=503,
                detail="No printer configured. Set the PRINT_PRINTER "
                       "environment variable to a queue name from "
                       "Get-Printer (docs/windows-printing.md).")

    # Fast actionable check before spinning up the pipeline thread
    if not os.path.isfile(config.FORM_TEMPLATE_PATH):
        raise HTTPException(
            status_code=503,
            detail="Laptop Form template is not configured on the server. "
                   "An administrator must set FORM_TEMPLATE_PATH "
                   "(docs/windows-printing.md).")

    # ── best-effort Snipe-IT enrichment (failure tolerated) ───────────────────
    snipe = None
    serial = (data or {}).get("serial")
    if serial:
        try:
            asset: SnipeItAsset = await client.get_asset_by_serial(serial)
            snipe = laptop_form.asset_form_record(asset)
        except (SnipeItError, ValueError):  # network / config / lookup issues
            snipe = None                 # the form still prints with agent data

    # ── fill → convert → submit (blocking; off the event loop) ────────────────
    try:
        result = await asyncio.to_thread(
            laptop_form.assemble_and_print, data, snipe, printer, code)
    except laptop_form.LaptopFormError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except printing.PrintingError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return JSONResponse(result)
