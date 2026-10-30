# Snipe-IT Device Onboarding (Handover Portal)

IT opens the portal, gets a short session code, runs an agent one-liner on
the employee's device; the agent POSTs its report back using that code.

## Project structure

```
main.py                 # compatibility entry point (uvicorn main:app still works)
app/
  main.py               # create_app(), router wiring, middleware; `app = create_app()`
  config.py             # the ONLY place env vars are read
  dependencies.py       # current_user, injectable session store
  auth.py               # Entra ID SSO: /login, /auth/callback, /logout
  schemas.py            # AgentPayload
  db/
    base.py             # declarative Base + stable constraint names
    engine.py           # lazy async engine/sessionmaker (no connection at import)
    models/handover.py  # Handover, HandoverStage, AgentReport, Document, Event
  repositories/events.py  # insert-only business event trail
  services/sessions.py  # SessionStore (create/get/submit/expire)
  routers/
    pages.py            # / and /api/me
    agent.py            # /api/session/new, /data, /submit
    snipeit.py          # /api/snipeit/device, /api/snipeit/health
    health.py           # /api/health
    diag.py             # /diag/clipboard (behind ENABLE_DIAG)
alembic/                # async migrations (alembic upgrade head)
alembic.ini
templates/              # index.html, diag_clipboard.html
  partials/logo.html    # app logo (Jinja macro: mark + lockup)
static/
  css/app.css           # built stylesheet (generated — do not edit)
  favicon.svg           # app icon
  app.js                # portal UI (uses shared copyText)
  js/clipboard.js       # shared copyText() utility (3 tiers, never silent)
  js/theme.js           # light / dark / system theme toggle
  agent.ps1 / agent.sh  # device agent scripts served to targets
styles/app.css          # Tailwind + shadcn design-system source
tests/
  conftest.py           # env-isolated app factory (see header comment)
  test_characterization.py  # pins current API behavior (must stay green)
  test_diag.py          # diagnostics page tests
  test_architecture_rules.py  # enforces the layer dependency rules (ARC-01/04/05)
  test_graph_consistency.py   # keeps the LIVE GRAPH in docs/principles/03 honest
  test_persistence.py   # migration, partial index, lazy engine, event trail
  test_clipboard_playwright.py  # browser condition matrix (needs browsers)
pytest.ini              # asyncio_mode=auto, testpaths=tests
.gitattributes          # LF line endings; binary markers for images/fonts
docs/
  discovery.md          # code map produced before the refactor
  copy-diagnosis.md     # clipboard root cause, decision log, manual matrix
  https-deployment.md   # deferred TLS cutover checklist
  logo.svg              # brand mark (512px app icon)
  OPEN_QUESTIONS.md     # questions the prompt does not answer (conservative default taken)
  principles/           # H-Caliper: the 12 principle files (01…12)
  context/              # briefing material dropped by the owner
```

## UI system

The frontend is server-rendered (Jinja2 + vanilla JS) styled with
**Tailwind CSS v4** and the **shadcn/ui** token architecture.

- `styles/app.css` is the single source of truth: design tokens (oklch CSS
  variables with the canonical shadcn names), the light/dark palettes, and the
  shadcn component classes (`.card`, `.btn`, `.badge`, `.table`, `.tabs-*`,
  `.alert`, `.input`, `.separator`).
- `static/css/app.css` is the **build output** served at `/static/css/app.css`.
  It is committed so the Python app can be deployed without Node.
- Class names mirror the shadcn component APIs, so a future React port is a
  mechanical translation.

### Page layout

```
┌──────────────────────────────────────────────────────────┐
│ topbar: logo · wordmark · clock · user · theme toggle    │
├──────────────────────────────────────────────────────────┤
│ Local Agent  (full width — primary action)               │
│   session code → platform tabs → one-line command + copy  │
│   guidance steps → live status                            │
├────────────────────────────┬─────────────────────────────┤
│ Reported by the agent      │ This device                 │
│   System / Processor / …   │   Browser & OS / Graphics / │
│   Windows activation        │   Battery                   │
│   Software inventory        │ Snipe-IT record             │
└────────────────────────────┴─────────────────────────────┘
```

The agent panel spans the full width so the one-liner command never wraps,
and the two data columns are grouped by origin (agent-reported vs. collected
in this browser).

### Logo

- `templates/partials/logo.html` — Jinja macro `logo_mark(size)` /
  `logo_lockup(size, title, subtitle)`. Strokes only, inherits `currentColor`,
  so it adapts to the active theme.
- `static/favicon.svg` — app icon (browser tab).
- `docs/logo.svg` — 512px brand mark.

### Theme (light / dark / system)

- Dark mode is class-driven: `<html class="dark">`, not media-driven, so the
  user choice overrides the OS preference.
- An inline script in `<head>` applies the theme **before first paint** — the
  page never flashes the wrong colours.
- The topbar button cycles **light → dark → system**. The choice is persisted
  in `localStorage` under `theme`; `system` removes the key and follows
  `prefers-color-scheme`.
- Programmatic API: `window.theme.set('light'|'dark'|'system')`,
  `window.theme.get()`, `window.theme.effective()`.

### Build the stylesheet

```powershell
npm install
npm run build:css   # one-shot build -> static/css/app.css
npm run dev         # rebuild on change (watch mode)
```

Rebuild is required after changing `styles/app.css`, the templates, or any
Tailwind classes used in `static/app.js`.

## Run

```powershell
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080
# (equivalent: python -m uvicorn app.main:app --host 0.0.0.0 --port 8080)
```

Copy `.env.example` to `.env` and fill it in. SSO is ON unless
`SSO_ENABLED=false` (development only — startup prints a warning).

## Database

PostgreSQL is the production target (`DATABASE_URL=postgresql+asyncpg://…`);
SQLite is used for local development and tests
(`sqlite+aiosqlite:///./data/handover.db`, the default). The schema is managed
only by Alembic — the application never calls `create_all`:

```powershell
alembic upgrade head      # create/upgrade the schema
alembic downgrade base    # drop everything (development only)
```

Set `TEST_DATABASE_URL` to run the migration test against PostgreSQL; without
it that test is reported as skipped ("PostgreSQL not exercised").

## Tests

```powershell
# fast API tests (no network, no browser)
python -m pytest tests/test_characterization.py tests/test_diag.py -q

# browser matrix (needs Playwright browsers once):
python -m playwright install chromium firefox webkit
python -m pytest tests/test_clipboard_playwright.py -q

# everything
python -m pytest tests/ -q
```

## Diagnostics

Set `ENABLE_DIAG=true`, restart, open `/diag/clipboard` on a failing and a
working device, and paste the report into the matrix in
`docs/copy-diagnosis.md`. See also `docs/https-deployment.md`.
