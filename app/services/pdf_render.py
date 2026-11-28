"""Best-effort DOCX to PDF conversion.

Microsoft Word (via ``docx2pdf``, Windows only) is the primary converter.
LibreOffice (isolated profile) is the fallback when Word is missing or fails;
it is found, in order, from ``SOFFICE_PATH``, the ``PATH`` and the standard
Windows install folders.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from app import config

log = logging.getLogger(__name__)

_WINDOWS_SOFFICE_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


def find_soffice() -> str | None:
    """Return the LibreOffice executable, or None when it is not installed."""
    configured = (config.SOFFICE_PATH or "").strip()
    if configured:
        if os.path.isfile(configured):
            return configured
        log.warning("SOFFICE_PATH does not point to a file: %s", configured)
    on_path = shutil.which("soffice") or shutil.which("libreoffice")
    if on_path:
        return on_path
    for candidate in _WINDOWS_SOFFICE_PATHS:
        if os.path.isfile(candidate):
            return candidate
    return None


def _word_converter():
    """The docx2pdf ``convert`` function on Windows, else None (never raises)."""
    if sys.platform != "win32":
        return None
    try:
        from docx2pdf import convert  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional dependency, any import problem
        return None
    return convert


def pdf_print_available() -> bool:
    """True when some converter is installed (used by the health endpoint)."""
    return find_soffice() is not None or _word_converter() is not None


def docx_to_pdf(docx_bytes: bytes) -> bytes | None:
    """Convert with Microsoft Word first (Windows), then LibreOffice."""
    word = _word_converter()
    if word is not None:
        pdf = _convert_with_word(word, docx_bytes)
        if pdf is not None:
            return pdf
    executable = find_soffice()
    if not executable:
        log.warning(
            "PDF conversion unavailable: neither Microsoft Word (docx2pdf) "
            "nor LibreOffice is available"
        )
        return None
    try:
        with tempfile.TemporaryDirectory(prefix="handover-pdf-") as directory:
            root = Path(directory)
            source = root / "handover.docx"
            source.write_bytes(docx_bytes)
            subprocess.run(
                [
                    executable, "--headless",
                    f"-env:UserInstallation={root.joinpath('profile').as_uri()}",
                    "--convert-to", "pdf", "--outdir", str(root), str(source),
                ],
                check=True, capture_output=True, timeout=60,
            )
            output = root / "handover.pdf"
            return output.read_bytes() if output.is_file() else None
    except (OSError, subprocess.SubprocessError):
        log.exception("PDF conversion failed")
        return None


def _com_init():
    """Initialise COM on this thread when pywin32 is present; else None."""
    try:
        import pythoncom  # type: ignore[import-not-found]
    except Exception:  # noqa: BLE001 - optional, only present with pywin32
        return None
    pythoncom.CoInitialize()
    return pythoncom


def _convert_with_word(convert, docx_bytes: bytes) -> bytes | None:
    try:
        with tempfile.TemporaryDirectory(prefix="handover-pdf-") as directory:
            root = Path(directory)
            source = root / "handover.docx"
            output = root / "handover.pdf"
            source.write_bytes(docx_bytes)
            # Word is driven through COM, which must be initialised on the
            # calling thread (the request thread is not a COM thread).
            com = _com_init()
            try:
                convert(str(source), str(output))
            finally:
                if com is not None:
                    com.CoUninitialize()
            return output.read_bytes() if output.is_file() else None
    except Exception:  # noqa: BLE001 - Word/COM failures are many and opaque
        log.exception("PDF conversion through Microsoft Word failed")
        return None
