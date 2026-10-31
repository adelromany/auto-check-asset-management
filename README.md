# Snipe-IT Device Onboarding (Handover Portal)

IT opens the portal, runs a short-lived agent on the employee's device, and
works through ten verifiable handover stages. Snipe-IT stays the system of
record; the portal stores workflow state and evidence, and only writes to
Snipe-IT after an engineer's explicit, verified action.

For installation on another computer, see the [Windows deployment guide](docs/deployment/INSTALL-WINDOWS.md), [Linux/macOS draft](docs/deployment/INSTALL-LINUX-MAC.md), and [troubleshooting guide](docs/deployment/TROUBLESHOOTING.md).

## Project structure

```
main.py                    # compatibility entry point (uvicorn main:app still works)
app/
  main.py                  # create_app(), middleware, router wiring; `app = create_app()`
  config.py                # the ONLY place env vars are read
  dependencies.py          # current_user, DB session, Snipe-IT client, session store
  auth.py                  # Entra ID SSO: /login, /auth/callback, /logout
  schemas.py               # AgentPayload
  security/
    startup.py             # fail closed when SSO is on and SESSION_SECRET is a placeholder
    csrf.py                # per-session token + Origin check for cookie-authenticated writes
    headers.py             # self-only CSP and fixed security headers
    ratelimit.py           # in-memory limits for agent submit and recipient search
  middleware/
    request_id.py          # request IDs and generic 500 response correlation
  logging_config.py       # structured technical logging configuration
  db/
    base.py                # declarative Base + stable constraint names
    engine.py              # lazy async engine/sessionmaker (no connection at import)
    models/handover.py     # Handover, HandoverStage, AgentReport, Document, Event
  domain/
    stages.py              # ten fixed stages, order, dependencies, statuses
    handover_rules.py      # pure derive_status / missing_steps / can_run
    software_rules.py      # pure hardware, software and activation checks
    recipient_identity.py  # domain-user and engineer-match detection
    timeutil.py            # normalize persistence datetimes to UTC
    errors.py              # typed handover workflow errors
    redaction.py           # strip windows_activation.partial_key before storage
  clients/
    snipeit.py             # SnipeItClient, credential provider, typed results
  dto/
    handover.py            # handover request/response models
    dashboard.py           # dashboard summary and paged-row models
  repositories/
    handovers.py           # handover, stage and agent-report data access
    documents.py           # stored evidence document data access
    events.py              # insert-only business event trail
  services/
    sessions.py            # in-memory short-code SessionStore
    handovers.py           # create/get/list/confirm/cancel/recompute/agent report
    software_check.py      # software override and re-evaluation
    snipeit_ops.py         # recipient search/confirm, preview, checkin, verified checkout
    documents.py           # printable report, safe scan storage, download, verified push
    dashboard.py           # database-side aggregates and page-sized rows
  routers/
    pages.py               # /, /handovers, /handovers/{id}, /api/me
    agent.py               # /api/session/new, /data, /submit
    handovers.py           # /api/handovers create/list/detail/stages/recipient/preview/checkin/checkout
    documents.py           # report page, document upload/download/push
    dashboard.py           # /api/dashboard/handovers/summary and /handovers
    snipeit.py             # /api/snipeit/device, /api/snipeit/health
    health.py              # /api/health
    diag.py                # /diag/clipboard (behind ENABLE_DIAG)
    http_errors.py         # shared domain/client error -> HTTP mapping
alembic/                   # async migrations (alembic upgrade head)
alembic.ini
templates/
  index.html               # legacy agent landing page
  handovers.html           # dashboard page
  handover_detail.html     # case page
  handover_report.html     # printable report
  diag_clipboard.html      # clipboard diagnostics
  partials/                # logo, page head, topbar, labels
static/
  css/app.css              # built stylesheet (generated — do not edit)
  css/report.css           # printable report styles (self-hosted)
  js/clipboard.js          # shared copyText() utility (3 tiers)
  js/theme.js              # light / dark / system toggle
  js/theme-init.js         # pre-paint theme bootstrap (CSP-safe)
  js/shell.js              # topbar, clock, CSRF token bridge
  js/handovers.js          # dashboard filters, KPIs, table states
  js/handover_detail.js    # case-page actions
  js/software_check.js    # software override interaction
  js/diag_clipboard.js     # diagnostics page logic
  app.js                   # legacy landing-page UI (not extended for the dashboard)
  agent.ps1 / agent.sh     # device agent scripts
styles/app.css             # Tailwind + shadcn design-system source
tests/
  conftest.py              # env-isolated app factory
  test_characterization.py # 25 original compatibility tests
  test_diag.py             # 4 original diagnostics tests
  test_architecture_rules.py
  test_graph_consistency.py
  test_principles_visual.py
  test_persistence.py
  test_handovers_api.py
  test_handover_service.py
  test_snipeit_client.py
  test_snipeit_write_ops.py
  test_documents.py
  test_dashboard.py
  test_security_hardening.py
  test_clipboard_playwright.py  # browser matrix
docs/
  principles/              # H-Caliper: the 12 principle files (01…12)
    visual/                # generated, offline HTML versions of the principles
  security-review.md       # Phase 8 checklist against principle 04
  snipeit-api-verified.md  # verified API surface / live-verification status
  OPEN_QUESTIONS.md        # open questions and the conservative option taken
  https-deployment.md      # deferred TLS cutover checklist
  copy-diagnosis.md        # clipboard root cause and manual matrix
  discovery.md             # code map produced before the refactor
```

## Principle visuals

The Markdown files in `docs/principles/` remain the source of truth. Build
their offline HTML versions with `python tools/build_principles_visual.py`.
The generated `handover-workflow.html` explains the code-defined device handover flow; build it directly with `python tools/build_handover_workflow.py`.
Check that committed visuals are current with
`python tools/build_principles_visual.py --check`. Open
`docs/principles/visual/index.html` in a browser to read them.

## UI system

The frontend is server-rendered (Jinja2 + vanilla JS) styled with
**Tailwind CSS v4** and the **shadcn/ui** token architecture.

- `styles/app.css` is the single source of truth: design tokens, light/dark
  palettes and the component classes (`.card`, `.btn`, `.badge`, `.table`,
  `.tabs-*`, `.alert`, `.input`, `.separator`).
- `static/css/app.css` is the build output served at `/static/css/app.css`.
  It is committed so the Python app can be deployed without Node.
- `static/css/report.css` is a small standalone stylesheet for the printable
  report; the report does not load the full app stylesheet.

### Pages

- `/` — the original agent landing page, with one **Start handover** link.
- `/handovers` — KPI tiles (Completed, In progress, Stalled, Total), filters
  (status, engineer, date range), and a table with status badge, serial,
  recipient, engineer, stage progress and a **Missing** column.
- `/handovers/{id}` — the case page: stage checklist with actions, recipient
  reported vs confirmed, the recipient's Snipe-IT devices with Checkin, the
  new device with Checkout, signed-sheet attach/push, dry-run preview and the
  event timeline.

Every table has loading, empty and populated states. Every action gives a
toast or alert. Dynamic data is inserted with `textContent` or Jinja
autoescape, never `innerHTML`.

### Theme

- Dark mode is class-driven (`<html class="dark">`).
- `static/js/theme-init.js` is loaded synchronously in `<head>` and applies the
  stored theme before first paint. It is external so the CSP can stay
  inline-free.
- The topbar button cycles **light → dark → system**; the choice is stored in
  `localStorage` under `theme`.
- Programmatic API: `window.theme.set('light'|'dark'|'system')`,
  `window.theme.get()`, `window.theme.effective()`.

### Build the stylesheet

```powershell
npm install
npm run build:css   # one-shot build -> static/css/app.css
npm run dev         # rebuild on change (watch mode)
```

Rebuild after changing `styles/app.css`, the templates, or Tailwind classes
used in the JS.

## Security

- `SSO_ENABLED=true` with an empty or `change-me` `SESSION_SECRET` refuses to
  start. Generate a real secret, for example
  `python -c "import secrets; print(secrets.token_hex(32))"`.
- State-changing requests under `/api/handovers` and `/api/dashboard` require
  `X-CSRF-Token`; the token is delivered in the `X-CSRF-Token` response header
  of `GET /api/me`. A present `Origin` must match the request host.
- Every response carries `nosniff`, `Referrer-Policy: same-origin`,
  `X-Frame-Options: DENY` and a self-only CSP. No CDN, external font or inline
  script/style is allowed.
- Agent submit and recipient search are rate limited in memory (single
  process; see Q-4).
- Uploads are validated by magic bytes, capped while streaming, stored under
  UUID names, hashed with SHA-256 and downloaded only by an authenticated
  user.
- The full checklist and the remaining gaps are in `docs/security-review.md`.

## Run the local development stack (Windows)

From the repository root, run these commands in PowerShell:

```powershell
Set-Location D:\DevOps\B_labs\auto-check-asset-management
.\deploy\snipeit-dev\bootstrap.ps1
python -m alembic upgrade head
$env:SSO_ENABLED = "false"
python -m uvicorn main:app --host 127.0.0.1 --port 8080
```

The bootstrap creates/updates the ignored environment settings and starts
Snipe-IT. Use the development login documented in
`deploy/snipeit-dev/README.md`; do not reuse it outside this local instance.

## Manual Run

```powershell
pip install -r requirements.txt
copy .env.example .env   # fill in SESSION_SECRET and SSO values
python -m alembic upgrade head
python -m uvicorn main:app --host 0.0.0.0 --port 8080
# equivalent: python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

The portal listens at <http://localhost:8080>. The development Snipe-IT
instance listens at <http://localhost:8081>; its defaults are in
`deploy/snipeit-dev/.env.example`. Root `.env.example` points the portal to
that instance and leaves `SNIPEIT_TOKEN` blank until the bootstrap creates it.

`SSO_ENABLED=false` is a development bypass only; startup logs a warning.
Production runs with SSO on and HTTPS on. Software checks use
`REQUIRED_SOFTWARE_IDS`; a justified override is audited. `STALL_HOURS=24`
currently proposes an inactivity threshold; set `0` to disable while the
owner decision remains open.

## Database

PostgreSQL is the production target
(`DATABASE_URL=postgresql+asyncpg://…`); SQLite is used for local development
and tests (`sqlite+aiosqlite:///./data/handover.db`, the default). The schema
is managed only by Alembic — the application never calls `create_all`:

```powershell
alembic upgrade head      # create/upgrade the schema
alembic downgrade base    # drop everything (development only)
```

Set `TEST_DATABASE_URL` to run the migration test against PostgreSQL; without
it that test is skipped as "PostgreSQL not exercised". PostgreSQL migration
and coverage measurements are reported in the verification result for this
change.

## Tests

```powershell
# original compatibility contract (29 tests)
python -m pytest tests/test_characterization.py tests/test_diag.py -q

# everything that does not need a browser
python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py

# browser matrix (needs Playwright browsers once)
python -m playwright install chromium firefox webkit
python -m pytest tests/test_clipboard_playwright.py -q
```

Final verification on 2026-10-31: **345 passed, 6 skipped** for the fast suite
with PostgreSQL enabled; **23 passed, 2 skipped, 2 xfailed** for the browser
suite; **93% app coverage**. The six skipped fast-suite tests are the opt-in
live Snipe-IT checks, run separately against the local v8.8.3 instance (6
passed).

## Local Snipe-IT

`deploy/snipeit-dev/` contains a development-only Snipe-IT v8 + MariaDB
Compose stack and a repeatable bootstrap for local testing. The verified API
shapes and live-test limits are in `docs/snipeit-api-verified.md`.

## Diagnostics

Set `ENABLE_DIAG=true`, restart, open `/diag/clipboard` on a failing and a
working device, and paste the report into the matrix in
`docs/copy-diagnosis.md`. See also `docs/https-deployment.md`.
