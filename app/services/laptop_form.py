"""Fill Laptop Form.docx with the laptop's inventory data and print it.

Pipeline:
  1. Load the admin-provided DOCX merge template (config.FORM_TEMPLATE_PATH).
  2. Replace {{...}} placeholders — latest agent inventory + best-effort
     Snipe-IT fields — keeping every bit of Word formatting untouched.
  3. Convert DOCX→PDF with an unattended converter (LibreOffice headless by
     default; Word COM exists but is NOT recommended on servers — see
     docs/windows-printing.md).
  4. Submit the PDF to a Windows print queue (app/services/printing.py).

This module is the mock seam for automated tests: routers only depend on
assemble_and_print(), which tests monkeypatch wholesale.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import tempfile
import uuid
from pathlib import Path

from datetime import datetime, timezone

from app import config
from app.services import printing

logger = logging.getLogger("app.printing")

TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

# Sentinel for multi-line values; written into runs as real Word line breaks.
BR = "\u2021\u2021"

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class LaptopFormError(RuntimeError):
    """Raised for template/conversion problems with an actionable message."""


# ──────────────────────────────────────────────────────────────────────────────
# value mapping — one human-readable value per {{token}}
# ──────────────────────────────────────────────────────────────────────────────

def _text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _disk_line(disk) -> str:
    if not isinstance(disk, dict):
        return _text(disk)
    name = _text(disk.get("name")) or "Unknown disk"
    size = disk.get("size_gb")
    dtype = _text(disk.get("type"))
    parts = [name]
    if size is not None and str(size).strip():
        parts.append(f"{size} GB")
    if dtype:
        parts.append(dtype)
    return " — ".join(parts)


def _cpu_family(value) -> str:
    """Short processor family, e.g. 'i7', 'Ultra 7', 'Ryzen 5'.

    The corporate form's SPECIFICATION column uses these short forms.
    """
    t = _text(value)
    if not t:
        return ""
    m = re.search(r"\bi([3-9])\b", t, re.IGNORECASE)      # i5 / i7 (i7-1355U too)
    if m:
        return f"i{m.group(1)}"
    m = re.search(r"\bUltra\s+([579])\b", t, re.IGNORECASE)
    if m:
        return f"Ultra {m.group(1)}"
    m = re.search(r"\bRyzen\s+([3579])\b", re.sub(r"[^\w\s]", " ", t),
                  re.IGNORECASE)
    if m:
        return f"Ryzen {m.group(1)}"
    for word in ("Xeon", "Celeron", "Pentium", "Athlon", "Snapdragon"):
        if word.lower() in t.lower():
            return word
    if "apple" in t.lower():
        m = re.search(r"\bM([1-4])\b", t)
        if m:
            return f"Apple M{m.group(1)}"
    return t


def _ram_short(value) -> str:
    """RAM as people write it on forms: 16, 32 — never '32.0'."""
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _text(value)
    return str(int(number)) if number.is_integer() else str(number)


def _os_full(data: dict) -> str:
    """'Windows 11 Pro 10.0.26100 (64-bit)' — all present parts joined."""
    parts = [_text(data.get("os_name")), _text(data.get("os_version"))]
    arch = _text(data.get("os_arch"))
    if arch:
        parts.append(f"({arch})")
    return " ".join(p for p in parts if p)


def asset_form_record(asset) -> dict:
    """The subset of a Snipe-IT asset the form filler reads.

    Keeps routers and services away from the client's dataclass: anything with
    the same attributes (``SnipeItAsset``) can be passed in.
    """
    return {
        "asset_tag": getattr(asset, "asset_tag", None),
        "name": getattr(asset, "name", None),
        "status": getattr(asset, "status", None),
        "assigned_to": getattr(asset, "assigned_to_name", None),
        "location": getattr(asset, "location", None),
        "purchase_date": getattr(asset, "purchase_date", None),
        "notes": getattr(asset, "notes", None),
    }


def build_mapping(
    data: dict, snipe: dict | None = None, extra: dict | None = None
) -> dict:
    """Flatten the agent payload + Snipe-IT record into template values.

    Multi-line values are joined with BR, written as real line breaks later.
    ``extra`` adds optional handover keys (recipient, engineer, asset tag,
    handover id, date) without changing any of the established keys.
    """
    disks = data.get("disks") or []
    disk_lines = [_disk_line(d) for d in disks]

    checks = data.get("software_checks") or []
    software_lines = []
    for check in checks:
        state = "installed" if check.get("installed") else "not installed"
        version = _text(check.get("version"))
        software_lines.append(
            f"{_text(check.get('name'))} "
            f"({state}{', v' + version if version else ''})"
        )

    ips = data.get("ip_addresses") or []
    ip_lines = [
        f"{_text(ip.get('iface'))}: {_text(ip.get('ip'))}"
        for ip in ips if isinstance(ip, dict)
    ]

    activation = data.get("windows_activation") or {}
    snipe = snipe or {}

    return {
        # ── agent inventory ──────────────────────────────────────────────
        "hostname":            _text(data.get("hostname")),
        "username":            _text(data.get("username")),
        "serial":              _text(data.get("serial")),
        "serial_number":       _text(data.get("serial")),          # alias
        "asset_id":            _text(data.get("serial")),          # alias
        "manufacturer":        _text(data.get("manufacturer")),
        "model":               _text(data.get("model")),
        "cpu":                 _text(data.get("cpu")),
        "cpu_cores":           _text(data.get("cpu_cores")),
        "cpu_family":          _cpu_family(data.get("cpu")),       # 'i7' / 'Ultra 7'
        "ram_gb":              _text(data.get("ram_gb")),
        "ram":                 _ram_short(data.get("ram_gb")),     # 32, never 32.0
        "disks":               BR.join(disk_lines),
        "disk1":               disk_lines[0] if disk_lines else "",  # first disk for label autofill
        "os_name":             _text(data.get("os_name")),
        "os_version":          _text(data.get("os_version")),
        "os_arch":             _text(data.get("os_arch")),
        "os_full":             _os_full(data),                     # name version (arch)
        "ip_addresses":        BR.join(ip_lines),
        "agent_os":            _text(data.get("agent_os")),
        "collected_at":        _text(data.get("collected_at")),
        "software_checks":     BR.join(software_lines),
        # ── Windows activation ───────────────────────────────────────────
        "windows_activation_status":      _text(activation.get("status")),
        "windows_activation_product":     _text(activation.get("product_name")),
        "windows_activation_partial_key": _text(activation.get("partial_key")),
        # ── best-effort Snipe-IT record ──────────────────────────────────
        "snipe_asset_tag":     _text(snipe.get("asset_tag")),
        "snipe_name":          _text(snipe.get("name")),
        "snipe_status":        _text(snipe.get("status")),
        "snipe_assigned_to":   _text(snipe.get("assigned_to")),
        "snipe_location":      _text(snipe.get("location")),
        "snipe_purchase_date": _text(snipe.get("purchase_date")),
        "snipe_notes":         _text(snipe.get("notes")),
        # ── handover printing (optional; blank when the caller omits them) ──
        "recipient_name":      _text((extra or {}).get("recipient_name")),
        "recipient_username":  _text((extra or {}).get("recipient_username")),
        "engineer_name":       _text((extra or {}).get("engineer_name")),
        "asset_tag":           _text((extra or {}).get("asset_tag")),
        "handover_id":         _text((extra or {}).get("handover_id")),
        "print_date":          _text((extra or {}).get("print_date")),
    }


# ──────────────────────────────────────────────────────────────────────────────
# docx token replacement
# ──────────────────────────────────────────────────────────────────────────────

def _set_run_text_with_breaks(run, value: str) -> None:
    """Write run text; when it contains BR markers, emit real line breaks.

    python-docx will happily store '\n' inside <w:t>, but Word renders that as
    a space only. Word's own line break is the <w:br/> element, added here.
    """
    lines = value.split(BR)
    if len(lines) <= 1:
        run.text = value
        return
    run.text = lines[0]
    for line in lines[1:]:
        run._element.append(make("w:br"))
        if line:
            t = make("w:t")
            t.text = line
            t.set(_W_NS + "space", "preserve")
            run._element.append(t)


def make(tag: str):
    from docx.oxml import OxmlElement
    return OxmlElement(tag)


def _apply_paragraph_tokens(paragraph, mapping: dict, unknown: set) -> int:
    """Replace {{tokens}} in one paragraph. Returns count of tokens replaced.

    Keeps the run (and thus its formatting) whenever the token does not span
    runs; tokens spanning runs are handled by collapsing the runs first, which
    preserves the paragraph format. Word templates authored normally rarely
    produce split tokens; the collapse path exists so nothing ever shows.

    Tokens the mapping does not know are blanked on paper and recorded in
    `unknown` so the admin can fix the template.
    """
    try:
        runs = paragraph.runs
    except AttributeError:        # non-standard paragraph wrappers
        return 0
    if not runs:
        return 0

    def _repl(m):
        key = m.group(1).lower()
        if key in mapping:
            return mapping[key]
        unknown.add(key)
        return ""                 # blank on paper, reported in the result

    replaced = 0
    for run in runs:
        text = run.text
        if "{" in text and TOKEN_RE.search(text):
            new_text, n = TOKEN_RE.subn(_repl, text)
            if BR in new_text:
                _set_run_text_with_breaks(run, new_text)
            elif n:
                run.text = new_text
            replaced += n
        elif BR in text:
            _set_run_text_with_breaks(run, text)
    if replaced:
        return replaced

    # a single token may be split across runs ({{ + }} pieces)
    joined = "".join(r.text for r in runs)
    if "{" not in joined:
        return 0
    new_text, n = TOKEN_RE.subn(_repl, joined)
    if not n:
        return 0
    first = runs[0]
    for extra in runs[1:]:
        extra.text = ""
    if BR in new_text:
        _set_run_text_with_breaks(first, new_text)
    else:
        first.text = new_text
    return n


def _fill_table(table, mapping: dict, unknown: set) -> int:
    """Replace tokens in (possibly nested) table cells. Returns count."""
    count = 0
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                count += _apply_paragraph_tokens(paragraph, mapping, unknown)
            for nested in cell.tables:
                count += _fill_table(nested, mapping, unknown)
    return count


# ──────────────────────────────────────────────────────────────────────────────
# label autofill — the corporate form has plain label cells (Model, Serial,
# Processor, RAM, ...), no {{tokens}}. For every recognized label the value is
# written into the EMPTY cell immediately to its right, so the original Word
# layout, fonts and RTL text are never touched or re-created.
# ──────────────────────────────────────────────────────────────────────────────

def _norm_label(text: str) -> str:
    """'Serial Number:' / 'RAM (GB)' / 'Hard Disk' → comparable key."""
    return re.sub(r"[\s:/\-_.,()&éè]+", "", _text(text)).lower()


LABEL_FILL = {
    # normalised label cell text → mapping key
    "model":                 "model",
    "modello":               "model",
    "serial":                "serial",
    "serialnumber":          "serial",
    "sn":                    "serial",
    "processor":             "cpu_family",
    "cpu":                   "cpu_family",
    "ram":                   "ram",
    "ramgb":                 "ram",
    "installedram":          "ram",
    "memory":                "ram",
    "os":                    "os_name",
    "operatingsystem":       "os_full",
    "harddisk":              "disk1",
    "harddrive":             "disk1",
    "storage":               "disk1",
    "ssd":                   "disk1",
    "hdd":                   "disk1",
    "user":                  "username",
    "username":              "username",
    "employee":              "username",
    "employeename":          "username",
    "device":                "hostname",
    "devicename":            "hostname",
    "hostname":              "hostname",
    "computername":          "hostname",
    "assettag":              "snipe_asset_tag",
    "location":              "snipe_location",
    "assignedto":            "snipe_assigned_to",
}


def _autofill_labeled_tables(document, mapping: dict) -> int:
    """Write values next to label cells (Model | , Processor | RAM | ...).

    Rules — deliberately conservative so a corporate template is never
    damaged:
      * only cells whose whole (trimmed) text is a known label are treated;
      * only the FIRST empty cell to the right of the label is filled;
      * existing text is never overwritten (the 'NO.' numbers, headers and
        pre-typed entries stay as the template author made them);
      * each label is filled at most once per document;
      * missing inventory values leave the cell blank, like the paper form.
    """
    filled = 0
    seen: set = set()

    tables = list(document.tables)
    for section in document.sections:
        tables += list(section.header.tables) + list(section.footer.tables)

    for table in tables:
        for row in table.rows:
            cells = row.cells
            for idx, cell in enumerate(cells):
                key = LABEL_FILL.get(_norm_label(cell.text))
                if not key or key in seen:
                    continue
                value = _text(mapping.get(key))
                if not value:
                    continue            # no data → cell stays like the template
                target_idx = idx + 1
                if target_idx >= len(cells):
                    continue            # label was a column header (e.g. 'Serial')
                target = cells[target_idx]
                if target.text.strip():
                    continue            # pre-filled — never overwrite
                target.paragraphs[0].add_run(value)
                seen.add(key)
                filled += 1
    return filled


def fill_document(data: dict, snipe: dict | None, template_path: str,
                  output_docx: str, extra: dict | None = None) -> dict:
    """Fill the merge template into output_docx.

    Returns {"tokens_replaced": int, "tokens_missing": [name,...]} — the
    missing list names template placeholders that had no matching inventory
    field (they are blanked on paper, and logged so the template can be fixed).
    """
    if not os.path.isfile(template_path):
        raise LaptopFormError(
            "Laptop Form template is not configured (FORM_TEMPLATE_PATH). "
            "Point it at an existing .docx template, or run "
            "scripts/make_laptop_form_template.py to generate a starter.")

    try:
        import docx  # python-docx
    except ModuleNotFoundError:
        raise LaptopFormError(
            "python-docx is not installed on the server. "
            "Run: pip install -r requirements.txt")

    mapping = build_mapping(data, snipe, extra)
    document = docx.Document(template_path)

    unknown: set = set()          # template tokens the mapping doesn't supply
    tokens_replaced = 0
    for paragraph in document.paragraphs:
        tokens_replaced += _apply_paragraph_tokens(paragraph, mapping, unknown)
    for table in document.tables:
        tokens_replaced += _fill_table(table, mapping, unknown)
    for section in document.sections:
        for part in (section.header, section.footer):
            for paragraph in part.paragraphs:
                tokens_replaced += _apply_paragraph_tokens(
                    paragraph, mapping, unknown)
            for hf_table in part.tables:
                tokens_replaced += _fill_table(hf_table, mapping, unknown)

    # Corporate forms authored as plain label cells (Model |, Serial |,
    # Processor |, RAM | ...) without {{tokens}}: write the specs into the
    # empty cell to the right of each label. Never overwrites anything.
    labels_filled = 0
    if config.PRINT_AUTOFILL_LABELS:
        labels_filled = _autofill_labeled_tables(document, mapping)

    # Scan the final XML for tokens we could not touch at all (e.g. inside
    # hyperlink fields) — they would still print raw braces.
    xml = document.element.xml
    untouched = {m.lower()
                 for m in re.findall(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}", xml)}
    tokens_missing = sorted(unknown | untouched)

    document.save(output_docx)
    logger.info(
        "Filled Laptop Form from %s: tokens=%d labels=%d missing=%s",
        template_path, tokens_replaced, labels_filled, tokens_missing or "-")
    return {
        "tokens_replaced": tokens_replaced,
        "labels_filled": labels_filled,
        "tokens_missing": tokens_missing,
    }


# ──────────────────────────────────────────────────────────────────────────────
# DOCX → PDF conversion (unattended)
# ──────────────────────────────────────────────────────────────────────────────

def convert_to_pdf(docx_path: str, output_dir: str,
                   timeout: int | None = None) -> str:
    """Convert one .docx to .pdf, return the PDF path. Converter per config.

    Tool-absence problems surface as LaptopFormError (a server configuration
    issue → HTTP 503), never as PrintingError (a spooler issue → HTTP 502).
    """
    converter = config.PRINT_PDF_CONVERTER
    timeout = timeout or config.PRINT_TIMEOUT_SECONDS
    try:
        if converter == "libreoffice":
            return _convert_libreoffice(docx_path, output_dir, timeout)
        if converter == "word_com":
            return _convert_word_com(docx_path, output_dir, timeout)
        raise LaptopFormError(
            f"PRINT_PDF_CONVERTER='{converter}' is not supported. "
            f"Use 'libreoffice' (recommended) or 'word_com'.")
    except printing.PrintingError as exc:
        raise LaptopFormError(str(exc)) from None


def _convert_libreoffice(docx_path: str, output_dir: str, timeout: int) -> str:
    """Unattended DOCX to PDF conversion using LibreOffice."""

    import shutil
    from pathlib import Path

    soffice = printing._find_soffice()

    if not soffice or not os.path.isfile(soffice):
        raise LaptopFormError(
            f"LibreOffice executable not found: {soffice}"
        )

    # Use a unique temporary profile for every conversion.
    profile = tempfile.mkdtemp(
        prefix=f"lo-profile-{os.getpid()}-"
    )

    profile_uri = Path(profile).resolve().as_uri()

    # Use absolute paths to avoid working-directory issues.
    docx_path = os.path.abspath(docx_path)
    output_dir = os.path.abspath(output_dir)

    os.makedirs(output_dir, exist_ok=True)

    pdf_path = os.path.join(
        output_dir,
        os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"
    )

    args = [
        soffice,
        f"-env:UserInstallation={profile_uri}",
        "--headless",
        "--nologo",
        "--nodefault",
        "--nofirststartwizard",
        "--norestore",
        "--convert-to",
        "pdf:writer_pdf_Export",
        "--outdir",
        output_dir,
        docx_path,
    ]

    logger.info("LibreOffice executable: %s", soffice)
    logger.info("LibreOffice profile: %s", profile_uri)
    logger.info("Converting DOCX: %s", docx_path)
    logger.info("PDF output directory: %s", output_dir)

    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(
                subprocess, "CREATE_NO_WINDOW", 0
            ),
        )

        logger.info(
            "LibreOffice return code: %s",
            completed.returncode
        )

        if completed.stdout:
            logger.info(
                "LibreOffice stdout: %s",
                completed.stdout.strip()
            )

        if completed.stderr:
            logger.warning(
                "LibreOffice stderr: %s",
                completed.stderr.strip()
            )

        if completed.returncode != 0:
            raise LaptopFormError(
                "LibreOffice conversion failed. "
                f"Return code: {completed.returncode}. "
                f"Detail: {(completed.stderr or completed.stdout)[:1000]}"
            )

        if not os.path.isfile(pdf_path):
            raise LaptopFormError(
                "LibreOffice exited without producing the expected PDF. "
                f"Expected: {pdf_path}. "
                f"Output: {(completed.stdout or '')[:1000]}"
            )

        if os.path.getsize(pdf_path) == 0:
            raise LaptopFormError(
                f"LibreOffice generated an empty PDF: {pdf_path}"
            )

        logger.info(
            "PDF conversion successful: %s (%d bytes)",
            pdf_path,
            os.path.getsize(pdf_path)
        )

        return pdf_path

    except subprocess.TimeoutExpired:
        raise LaptopFormError(
            f"LibreOffice conversion timed out after {timeout} seconds."
        ) from None

    except FileNotFoundError:
        raise LaptopFormError(
            f"Cannot execute LibreOffice: {soffice}"
        ) from None

    finally:
        # Remove the isolated LibreOffice profile.
        shutil.rmtree(profile, ignore_errors=True)


def _convert_word_com(docx_path: str, output_dir: str, timeout: int) -> str:
    """DOCX→PDF via Microsoft Word automation.

    ⚠ Microsoft does not recommend or support server-side automation of
    Office applications, and Word may not clean up under a service account
    session. PRINT_PDF_CONVERTER=libreoffice is the supported default; this
    path is kept for sites that already licensed and validated Word/COM.
    """
    try:
        import pythoncom
        import win32com.client        # noqa: F401  (pywin32)
    except ModuleNotFoundError:
        raise LaptopFormError(
            "PRINT_PDF_CONVERTER=word_com requires pywin32 on the server "
            "('pip install pywin32'), or switch to PRINT_PDF_CONVERTER="
            "libreoffice.")
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        document = word.Documents.Open(os.path.abspath(docx_path), ReadOnly=True)
        pdf_path = os.path.abspath(
            os.path.join(output_dir,
                         os.path.splitext(os.path.basename(docx_path))[0] + ".pdf"))
        document.SaveAs2(pdf_path, FileFormat=17)   # 17 = wdFormatPDF
        document.Close(False)
        document = None
    finally:
        try:
            if word is not None:
                word.Quit(False)
        except Exception:
            pass
        pythoncom.CoUninitialize()
    if not os.path.isfile(pdf_path):
        raise LaptopFormError("Word COM conversion produced no PDF file.")
    return pdf_path


# ──────────────────────────────────────────────────────────────────────────────
# pipeline entry — the seam tests replace
# ──────────────────────────────────────────────────────────────────────────────

def _safe_name(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", code) or "session"


def assemble_and_print(data: dict, snipe: dict | None, printer_name: str,
                       code: str, extra: dict | None = None) -> dict:
    """Fill → convert → submit. Returns an API-shaped result dict.

    Blocking (subprocesses); routers call it via asyncio.to_thread.
    """
    started = time.monotonic()
    output_dir = config.FORM_OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"AssetForm_{_safe_name(code)}_{stamp}"
    docx_path = os.path.join(output_dir, base + ".docx")

    fill_result = fill_document(
        data, snipe, config.FORM_TEMPLATE_PATH, docx_path, extra
    )

    converter_started = time.monotonic()
    pdf_path = convert_to_pdf(docx_path, output_dir)
    logger.info(
        "Rendered Laptop Form for session %s (asset=%s/%s) in %.2fs "
        "(converter=%.2fs, printer='%s')",
        code, _text(data.get("hostname")), _text(data.get("serial")),
        time.monotonic() - started, time.monotonic() - converter_started,
        printer_name)

    printing.run_ghostscript(pdf_path, printer_name)
    submitted_at = _utcnow_iso()

    # Snapshot the queue right after submission: "spooler accepted" and
    # "physically printed" are different things (docs/windows-printing.md).
    job = None
    try:
        for j in printing.query_jobs(printer_name):
            if (j.get("document_name") or "").startswith(base):
                job = {
                    "job_id": j.get("job_id"),
                    "status": j.get("job_status"),
                }
                break
    except printing.PrintingError:
        job = None    # queue enumeration hiccup — don't fail the submission

    logger.info(
        "Print submission ACCEPTED by spooler at %s: session=%s asset=%s/%s "
        "printer='%s' document='%s.pdf' job=%s",
        submitted_at, code, _text(data.get("hostname")),
        _text(data.get("serial")), printer_name, base,
        (job or {}).get("job_id", "unknown"))

    return {
        "status": "submitted",         # spooler accepted; see /api/print/jobs
        "printer": printer_name,
        "document_name": base,
        "docx": os.path.basename(docx_path),
        "pdf": os.path.basename(pdf_path),
        "submitted_at": submitted_at,
        "job": job,
        "tokens_missing": fill_result["tokens_missing"],
        "note": "Accepted by print spooler — check the physical output or "
                "poll /api/print/jobs for live job status.",
    }


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
