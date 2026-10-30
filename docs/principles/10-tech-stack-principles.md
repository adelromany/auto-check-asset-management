# 10 — Tech Stack Principles

## Approved
| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web | FastAPI, uvicorn, Jinja2, Starlette sessions |
| HTTP client | httpx (async) |
| Auth | authlib (Entra ID OIDC), itsdangerous |
| Validation | pydantic |
| Database | SQLAlchemy 2.x (async), Alembic; PostgreSQL via asyncpg (production target); SQLite via aiosqlite (development and tests) |
| Uploads | python-multipart |
| Frontend | Jinja templates, vanilla JS (ES modules), Tailwind CSS v4 CLI, shadcn token architecture |
| Tests | pytest, pytest-asyncio, pytest-cov, pytest-playwright |
| Local Snipe-IT | Docker Compose (development only) |

## Rules
- TEC-01 Nothing outside this table is added without the owner's approval. A proposed addition is written to `docs/OPEN_QUESTIONS.md` with the reason; it is not installed.
- TEC-02 Runtime dependencies in `requirements.txt`; test-only in `requirements-dev.txt`; both pinned with `>=` consistent with the existing file; exact installed versions recorded in the final sync.
- TEC-03 The application must run fully offline on a LAN: no CDN, no external fonts, no telemetry, no cloud services.
- TEC-04 No new frontend framework or bundler. The only build step is `npm run build:css`.
- TEC-05 Models use only portable column types (`Uuid`, `DateTime(timezone=True)`, `JSON` with a PostgreSQL JSONB variant, text, integers, booleans). No dialect-specific SQL in code.
- TEC-06 Configuration through environment variables read only in `app/config.py`; new variables documented in `.env.example` with safe placeholders.
- TEC-07 Single process, single worker is the supported deployment for the in-memory session-code store. Moving to multiple workers requires replacing that store first (recorded in decisions).
- TEC-08 The Snipe-IT API surface actually used is documented in `docs/snipeit-api-verified.md` with the Snipe-IT version it was verified against.
