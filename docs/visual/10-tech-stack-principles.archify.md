# 10 — Tech Stack Principles

Summary (generated from the headings): This page has 2 sections. It keeps every rule in the source file and adds no new rule.

## Approved and installed {#approved-and-installed-0}

| Layer | Technology | Installed version (2026-10-31) |
|---|---|---|
| Language {#language} | Python | 3.14.0 |
| Web {#web} | FastAPI | 0.143.0 |
| Web {#web-2} | Starlette | 1.7.0 |
| Web {#web-3} | uvicorn | 0.54.0 |
| Templates {#templates} | Jinja2 | 3.1.6 |
| HTTP client {#http-client} | httpx (async) | 0.28.1 |
| Auth {#auth} | authlib (Entra ID OIDC) | 1.8.0 |
| Auth {#auth-2} | itsdangerous | 2.2.0 |
| Validation {#validation} | pydantic | 2.14.0 |
| Config {#config} | python-dotenv | 1.2.3 |
| Database {#database} | SQLAlchemy 2.x (async) | 2.1.6 |
| Database {#database-2} | Alembic | 1.20.1 |
| Database {#database-3} | aiosqlite (development/tests) | 0.22.1 |
| Database {#database-4} | asyncpg (PostgreSQL driver) | 0.32.0 |
| Uploads {#uploads} | python-multipart | 0.0.32 |
| Frontend {#frontend} | Jinja templates, vanilla JS | — |
| Frontend {#frontend-2} | Tailwind CSS v4 CLI | 4.3.3 |
| Tests {#tests} | pytest | 9.1.1 |
| Tests {#tests-2} | pytest-asyncio | 1.4.1 |
| Tests {#tests-3} | pytest-cov | 7.1.0 |
| Tests {#tests-4} | pytest-playwright | declared; browser run result recorded in final verification |
| Local Snipe-IT {#local-snipe-it} | Docker Compose (development only) | v8.8.3 verified |

`requirements.txt` / `requirements-dev.txt` remain the source of the declared ranges; the table records what was actually present when the final sync ran.

## Rules {#rules-1}

| Rule | Text |
| --- | --- |
| TEC-01 {#tec-01} | Nothing outside this table is added without the owner's approval. A proposed addition is written to `docs/OPEN_QUESTIONS.md` with the reason; it is not installed. |
| TEC-02 {#tec-02} | Runtime dependencies in `requirements.txt`; test-only in `requirements-dev.txt`; both pinned with `>=` consistent with the existing file; exact installed versions recorded above. |
| TEC-03 {#tec-03} | The application must run fully offline on a LAN: no CDN, no external fonts, no telemetry, no cloud services. The self-only CSP enforces this for the browser. |
| TEC-04 {#tec-04} | No new frontend framework or bundler. The only build step is `npm run build:css`. |
| TEC-05 {#tec-05} | Models use only portable column types (`Uuid`, `DateTime(timezone=True)`, `JSON` with a PostgreSQL JSONB variant, text, integers, booleans). **Recorded exception:** the dashboard average-duration query uses one dialect-specific expression (`julianday` on SQLite, `extract('epoch', …)` on PostgreSQL), selected from the session bind in `app/services/dashboard.py`. It is read-only and covered by the dashboard tests. |
| TEC-06 {#tec-06} | Configuration through environment variables read only in `app/config.py`; new variables documented in `.env.example` with safe placeholders. |
| TEC-07 {#tec-07} | Single process, single worker is the supported deployment for the in-memory session-code store **and the in-memory rate limiter**. Moving to multiple workers requires replacing both stores first (D-52, Q-4). |
| TEC-08 {#tec-08} | The Snipe-IT API surface actually used is documented in `docs/snipeit-api-verified.md` with the Snipe-IT version it was verified against. v8.8.3 API and live tests were verified on 2026-10-31. |
| TEC-09 {#tec-09} | `pytest-cov` and `asyncpg` are installed; the PostgreSQL path was exercised in earlier verification. This change adds migration 0002, so final coverage and migration rerun results are recorded after verification (D-67). |

## Source {#source}

@facts
| Source Markdown | `docs/principles/10-tech-stack-principles.md` |
| SHA-256 | `aa9fdb93337e033e6c0bbd49524b658ecf3a33fbd4a3210cc18fcb6885acc7dc` |
| Repository link | [Open the Markdown source](https://github.com/adelromany/auto-check-asset-management/blob/main/docs/principles/10-tech-stack-principles.md) |
