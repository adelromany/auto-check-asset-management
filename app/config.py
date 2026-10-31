"""All environment-based settings. The ONLY place os.getenv is read.

Everything else imports values from here and reads them as module
attributes (never `from app.config import <value>` for anything the app
or tests may need fresh after a reload).
"""

import os

from dotenv import load_dotenv

load_dotenv()

SNIPEIT_URL = os.getenv("SNIPEIT_URL", "localhost:8000")
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

# In-memory rate limits (single process). Counts per client address per rule.
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_SUBMIT_PER_WINDOW = int(
    os.getenv("RATE_LIMIT_SUBMIT_PER_WINDOW", "60")
)
RATE_LIMIT_RECIPIENT_SEARCH_PER_WINDOW = int(
    os.getenv("RATE_LIMIT_RECIPIENT_SEARCH_PER_WINDOW", "60")
)

if not SSO_ENABLED:
    print("=" * 70)
    print("WARNING: SSO_ENABLED=false -> authentication is DISABLED.")
    print(f"Everyone is treated as '{DEV_USER['email']}'. NEVER use this in production.")
    print("=" * 70)
