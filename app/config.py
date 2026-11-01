"""All environment-based settings. The ONLY place os.getenv is read.

Everything else imports values from here and reads them as module
attributes (never `from app.config import <value>` for anything the app
or tests may need fresh after a reload).
"""

import os

from dotenv import load_dotenv

load_dotenv()

SNIPEIT_URL = os.getenv("SNIPEIT_URL", "http://localhost:8081")
SNIPEIT_TOKEN = os.getenv("SNIPEIT_TOKEN", "")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL", "600"))  # 10 min default
APP_HOST = os.getenv("APP_HOST", "localhost:8080")  # e.g. 192.168.1.50:8080

SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me")
HTTPS_ONLY = os.getenv("HTTPS_ONLY", "true") == "true"

AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
REDIRECT_URI = os.getenv("REDIRECT_URI")

SSO_ENABLED = os.getenv("SSO_ENABLED", "true").strip().lower() == "true"
DEV_USER = {
    "name": os.getenv("DEV_USER_NAME") or "Dev User",
    "email": os.getenv("DEV_USER_EMAIL") or "dev@local",
}

# Read-only clipboard diagnostics page (/diag/clipboard). Off by default.
ENABLE_DIAG = os.getenv("ENABLE_DIAG", "false").strip().lower() == "true"

# Handover portal persistence and Snipe-IT client.
# DATABASE_URL selects the driver: PostgreSQL (asyncpg) in production,
# SQLite (aiosqlite) for development and tests.
DATABASE_URL = os.getenv(
    "DATABASE_URL", "sqlite+aiosqlite:///./data/handover.db"
)
DOCUMENTS_DIR = os.getenv("DOCUMENTS_DIR", "./data/documents")
DOCUMENT_MAX_BYTES = int(os.getenv("DOCUMENT_MAX_BYTES", "10485760"))
SNIPEIT_TIMEOUT_SECONDS = float(os.getenv("SNIPEIT_TIMEOUT_SECONDS", "10"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
STALL_HOURS = int(os.getenv("STALL_HOURS", "24"))
REQUIRED_SOFTWARE_IDS = [
    item.strip().casefold()
    for item in os.getenv(
        "REQUIRED_SOFTWARE_IDS", "forticlient,sccm,intune,office2021"
    ).split(",")
    if item.strip()
]

# In-memory rate limits (single process). Counts per client address per rule.
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_SUBMIT_PER_WINDOW = int(
    os.getenv("RATE_LIMIT_SUBMIT_PER_WINDOW", "60")
)
RATE_LIMIT_RECIPIENT_SEARCH_PER_WINDOW = int(
    os.getenv("RATE_LIMIT_RECIPIENT_SEARCH_PER_WINDOW", "60")
)
# ── Windows printing — "Print Laptop Form" ────────────────────────────────────
# See docs/windows-printing.md for the full Windows Server setup steps.
#
# Laptop Form.docx merge template (created/edited in Word; placeholders are
# {{hostname}}, {{serial}}, ... — see scripts/make_laptop_form_template.py
# for a generated starting point).
FORM_TEMPLATE_PATH = os.getenv("FORM_TEMPLATE_PATH",
                               os.path.join("templates", "Laptop Form.docx"))

# Where filled .docx/.pdf artifacts are written (service account needs Modify).
FORM_OUTPUT_DIR = os.getenv("FORM_OUTPUT_DIR", os.path.join("var", "print"))

# Printer used by the app. ALWAYS admin-configured here — never the
# interactive user's default printer. Must match a Windows print queue name
# (the "Name" column of `Get-Printer`), e.g. "HP LaserJet M101-M106".
PRINT_PRINTER = os.getenv("PRINT_PRINTER", "")

# When true, authenticated users may pick any installed local printer per
# request (from those returned by GET /api/print/printers). Default off:
# only the admin-configured printer is honored.
PRINT_ALLOW_PRINTER_SELECTOR = (
    os.getenv("PRINT_ALLOW_PRINTER_SELECTOR", "false").strip().lower() == "true"
)

# docx→pdf converter: "libreoffice" (recommended unattended) or "word_com"
# (discouraged: Microsoft does not support server-side Office automation).
PRINT_PDF_CONVERTER = os.getenv("PRINT_PDF_CONVERTER", "libreoffice").strip().lower()

# Label autofill: corporate forms authored as plain label cells (Model |,
# Serial |, Processor |, RAM | ...) get their values written into the empty
# cell right of the label — no {{tokens}} needed in the Word file. Set to
# "false" to rely on {{tokens}} exclusively.
PRINT_AUTOFILL_LABELS = (
    os.getenv("PRINT_AUTOFILL_LABELS", "true").strip().lower() == "true"
)

# Optional explicit paths; when empty the module auto-detects on PATH plus
# standard install locations.
PRINT_SOFFICE_PATH = os.getenv("PRINT_SOFFICE_PATH", "")
PRINT_GHOSTSCRIPT_PATH = os.getenv("PRINT_GHOSTSCRIPT_PATH", "")

# Per-subprocess timeout for converter / spool submissions.
PRINT_TIMEOUT_SECONDS = int(os.getenv("PRINT_TIMEOUT_SECONDS", "120"))

# Optional dedicated log file (create_app wires it). When empty, printing
# logs flow to the default logger output (stdout under uvicorn).
PRINT_LOG_FILE = os.getenv("PRINT_LOG_FILE", "")
