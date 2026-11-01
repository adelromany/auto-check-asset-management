"""Windows print spooler integration for "Print Laptop Form".

Everything here talks to the Windows print system through PowerShell cmdlets
(`Get-Printer`, `Get-PrintJob`) and submits rendered PDFs to an installed
print queue via Ghostscript's `mswinpr2` device.

Design rules (docs/windows-printing.md):
  * No interactive user's default printer is ever consulted — the queue is
    either provided per request (admin-enabled selector) or comes from
    config.PRINT_PRINTER.
  * Every external process runs with an explicit timeout; failures surface as
   PrintingError with an actionable message (never raw traces).
  * On non-Windows hosts every function raises PrintingError — printing is a
    Windows Server feature; automated tests mock at this seam.

Submission semantics:
  * submit_pdf() returning successfully means the Windows print **spooler
    accepted the job** (Ghostscript exited 0). It does NOT guarantee paper
    came out. Job state afterwards is observable via query_jobs().
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from app import config

logger = logging.getLogger("app.printing")


class PrintingError(RuntimeError):
    """Raised for any printer-submission failure with an actionable message."""


def setup_logging() -> None:
    """Wire the optional PRINT_LOG_FILE file handler if configured.

    Called once from create_app(). Safe to call repeatedly.
    """
    if not config.PRINT_LOG_FILE:
        return
    if any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == os.path.abspath(config.PRINT_LOG_FILE)
        for h in logger.handlers
    ):
        return
    directory = os.path.dirname(os.path.abspath(config.PRINT_LOG_FILE))
    os.makedirs(directory, exist_ok=True)
    handler = logging.FileHandler(config.PRINT_LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.info("Print logging enabled -> %s", config.PRINT_LOG_FILE)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ──────────────────────────────────────────────────────────────────────────────
# subprocess plumbing
# ──────────────────────────────────────────────────────────────────────────────

def run_powershell(script: str, timeout: int | None = None) -> str:
    """Run a PowerShell command and return stdout. Raises PrintingError on failure.

    Uses -NoProfile/-NonInteractive/-ExecutionPolicy Bypass so the result is
    deterministic in any service context. Output encoding is forced to UTF-8.
    """
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command",
                "$ErrorActionPreference='Stop';"
                "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
                + script,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout or config.PRINT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise PrintingError(
            "powershell.exe not found. Printing requires Windows Server with "
            "Windows PowerShell 5.1 or newer.")
    except subprocess.TimeoutExpired as exc:
        raise PrintingError(
            f"The print-system command timed out after "
            f"{timeout or config.PRINT_TIMEOUT_SECONDS}s.")
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        raise PrintingError(f"Windows print system error: {stderr[:400]}")
    return completed.stdout


def run_ghostscript(pdf_path: str, printer_name: str, timeout: int | None = None):
    """Run gswin64c to spool one PDF onto a Windows printer queue."""
    args = [
        _find_ghostscript(),
        "-q",                       # be quiet
        "-dBATCH", "-dNOPAUSE",     # never wait for stdin (unattended!)
        "-dNoCancel",               # hide UI dialogs
        "-sDEVICE=mswinpr2",        # Windows spooler passthrough device
        f"-sOutputFile=%printer%{printer_name}", # -sOutputFile=%printer%<queue name>
        pdf_path,
    ]
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or config.PRINT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise PrintingError(
            "Ghostscript (gswin64c.exe) not found. Install it on the server or "
            "set PRINT_GHOSTSCRIPT_PATH (see docs/windows-printing.md).")
    except subprocess.TimeoutExpired:
        raise PrintingError(
            f"Print submission timed out after "
            f"{timeout or config.PRINT_TIMEOUT_SECONDS}s. The queue may be "
            f"offline or waiting for a form to load.")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise PrintingError(
            f"Ghostscript exited with code {completed.returncode} while "
            f"submitting to printer '{printer_name}'. Detail: {detail[:400]}")
    return completed


# ──────────────────────────────────────────────────────────────────────────────
# tool discovery (config path → PATH → usual install locations)
# ──────────────────────────────────────────────────────────────────────────────

def _search_ext_tools(name: str, *extra_dirs: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    base = os.environ.get("ProgramFiles", r"C:\Program Files")
    for d in extra_dirs:
        candidate = os.path.join(base, d, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _find_ghostscript() -> str:
    if config.PRINT_GHOSTSCRIPT_PATH:
        if not os.path.isfile(config.PRINT_GHOSTSCRIPT_PATH):
            raise PrintingError(
                "PRINT_GHOSTSCRIPT_PATH is set but does not point to an "
                "existing executable (gswin64c.exe).")
        return config.PRINT_GHOSTSCRIPT_PATH
    found = _search_ext_tools(
        "gswin64c.exe", "gs\\gs*\\bin", "Ghostscript\\bin")
    if not found:
        raise PrintingError(
            "Ghostscript is not installed (or not on PATH). Install "
            "Ghostscript for Windows so PDFs can be spooled to printers, or "
            "set PRINT_GHOSTSCRIPT_PATH.")
    return found


def _find_soffice() -> str:
    if config.PRINT_SOFFICE_PATH:
        if not os.path.isfile(config.PRINT_SOFFICE_PATH):
            raise PrintingError(
                "PRINT_SOFFICE_PATH is set but does not point to an existing "
                "executable (soffice.exe).")
        return config.PRINT_SOFFICE_PATH
    found = _search_ext_tools(
        "soffice.exe", "LibreOffice\\program", "LibreOffice\\program",
        "LibreOffice 24.2\\program", "LibreOffice 25.2\\program")
    if not found:
        raise PrintingError(
            "LibreOffice (soffice.exe) is not installed and "
            "PRINT_PDF_CONVERTER=libreoffice. Install LibreOffice or set "
            "PRINT_SOFFICE_PATH (see docs/windows-printing.md).")
    return found


# ──────────────────────────────────────────────────────────────────────────────
# public API
# ──────────────────────────────────────────────────────────────────────────────

def enumerate_printers() -> list[dict]:
    """List Windows print queues the server can print to.

    Returns a list of {name, type, status, work_offline} dicts — the names
    that are valid targets for submit_pdf(). No user context is involved.
    """
    raw = run_powershell(
        "Get-Printer | "
        "Select-Object Name, PrinterStatus, WorkOffline, Type | "
        "ConvertTo-Json -Compress"
    ).strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):      # ConvertTo-Json unwraps single-element lists
        data = [data]
    printers = []
    for item in data:
        printers.append({
            "name": item.get("Name"),
            "type": item.get("Type"),
            "status": item.get("PrinterStatus"),
            "work_offline": bool(item.get("WorkOffline")),
        })
    logger.info("Enumerated %d print queue(s) at %s", len(printers), _utcnow_iso())
    return printers


def printer_exists(printer_name: str) -> bool:
    """True when the named queue exists on this server (case-insensitive)."""
    if not printer_name:
        return False
    lowered = printer_name.lower()
    return any((p.get("name") or "").lower() == lowered
               for p in enumerate_printers())


def query_jobs(printer_name: str) -> list[dict]:
    """Return the current spooler jobs of one queue (Get-PrintJob).

    Lets the GUI distinguish 'submitted/accepted' from 'physically printed':
    once a job leaves the queue it is either fully printed or purged by an
    operator, both of which we surface honestly.
    """
    try:
        raw = run_powershell(
            f"Get-Printer -Name '{printer_name}' -ErrorAction Stop | Out-Null; "
            "Get-PrintJob -PrinterName '" + printer_name + "' | "
            "Sort-Object SubmittedTime | "
            "Select-Object Id, DocumentName, JobStatus, UserName, SubmittedTime | "
            "ConvertTo-Json -Compress"
        ).strip()
    except PrintingError as exc:
        # Unknown queue name → tell the caller rather than pretending the
        # queue is simply empty.
        if "not found" in str(exc).lower() or "Cannot find" in str(exc):
            raise PrintingError(
                f"Printer queue '{printer_name}' does not exist on this server.")
        raise
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [
        {
            "job_id": j.get("Id"),
            "document_name": j.get("DocumentName"),
            "job_status": j.get("JobStatus"),
            "user": j.get("UserName"),
            "submitted_time": j.get("SubmittedTime"),
        }
        for j in data
    ]
