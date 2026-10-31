# 10 — Tech Stack Principles

## Approved and installed

| Layer | Technology | Installed version (2026-10-31) |
|---|---|---|
| Language | Python | 3.14.0 |
| Web | FastAPI | 0.143.0 |
| Web | Starlette | 1.7.0 |
| Web | uvicorn | 0.54.0 |
| Templates | Jinja2 | 3.1.6 |
| HTTP client | httpx (async) | 0.28.1 |
| Auth | authlib (Entra ID OIDC) | 1.8.0 |
| Auth | itsdangerous | 2.2.0 |
| Validation | pydantic | 2.14.0 |
| Config | python-dotenv | 1.2.3 |
| Database | SQLAlchemy 2.x (async) | 2.1.6 |
| Database | Alembic | 1.20.1 |
| Database | aiosqlite (development/tests) | 0.22.1 |
| Database | asyncpg (production target) | **not installed here** |
| Uploads | python-multipart | 0.0.32 |
| Frontend | Jinja templates, vanilla JS | — |
| Frontend | Tailwind CSS v4 CLI | 4.3.3 |
| Tests | pytest | 9.1.1 |
| Tests | pytest-asyncio | 1.4.1 |
| Tests | pytest-cov | **not installed here** |
| Tests | pytest-playwright | declared; browsers not installed |
| Local Snipe-IT | Docker Compose (development only) | pull BLOCKED by network |

`requirements.txt` / `requirements-dev.txt` remain the source of the declared
ranges; the table records what was actually present when the final sync ran.

## Rules
- TEC-01 Nothing outside this table is added without the owner's approval. A proposed addition is written to `docs/OPEN_QUESTIONS.md` with the reason; it is not installed.
- TEC-02 Runtime dependencies in `requirements.txt`; test-only in `requirements-dev.txt`; both pinned with `>=` consistent with the existing file; exact installed versions recorded above.
- TEC-03 The application must run fully offline on a LAN: no CDN, no external fonts, no telemetry, no cloud services. The self-only CSP enforces this for the browser.
- TEC-04 No new frontend framework or bundler. The only build step is `npm run build:css`.
- TEC-05 Models use only portable column types (`Uuid`, `DateTime(timezone=True)`, `JSON` with a PostgreSQL JSONB variant, text, integers, booleans). **Recorded exception:** the dashboard average-duration query uses one dialect-specific expression (`julianday` on SQLite, `extract('epoch', …)` on PostgreSQL), selected from the session bind in `app/services/dashboard.py`. It is read-only and covered by the dashboard tests.
- TEC-06 Configuration through environment variables read only in `app/config.py`; new variables documented in `.env.example` with safe placeholders.
- TEC-07 Single process, single worker is the supported deployment for the in-memory session-code store **and the in-memory rate limiter**. Moving to multiple workers requires replacing both stores first (D-52, Q-4).
- TEC-08 The Snipe-IT API surface actually used is documented in `docs/snipeit-api-verified.md` with the Snipe-IT version it was verified against. Live verification is currently BLOCKED; the document records the failure and the owner steps.
- TEC-09 `pytest-cov` and `asyncpg` are approved but were not installable in this environment because package downloads time out. No coverage number and no PostgreSQL result is claimed until they are installed.
