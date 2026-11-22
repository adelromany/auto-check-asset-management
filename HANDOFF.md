# Handoff — fix/ui-recovery

## Delivered

The recovered UI provides Dashboard, Handovers, Maintenance and Sync under one
responsive light/dark shell. Handover and repair registration, maintenance
send/receive, operation drawers, case history, linked device Sync, clipboard
feedback, friendly errors, filters, table/board views and keyboard navigation
are implemented. Maintenance priority persists through Alembic migration 0006,
which also supplies governed defaults on migrated databases.

Canonical pages are `/`, `/handovers`, `/maintenance` and `/sync`; case pages
remain below `/handovers/{id}` or `/maintenance/{id}`. No runtime dependency was
added and domain/service/repository behavior was preserved.

## Start here

- UI design and route contract: `docs/ui/DESIGN.md`
- D1–D9 evidence, exact checks and limitations: `docs/ui/verification.md`
- Final screenshots and 400 px review sheets: `docs/review/`
- Clipboard diagnosis: `docs/ui/D9-clipboard.md`
- Snipe-IT API evidence and current live status: `docs/snipeit-api-verified.md`
- Open owner decisions: `docs/OPEN_QUESTIONS.md`

## Run

```powershell
python -m alembic upgrade head
$env:SSO_ENABLED = "false"  # development only
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Use the README for production/SSO configuration. Rebuild CSS after source or
class changes with `npm run build:css`; never edit `static/css/app.css` directly.
Regenerate principle visuals with `python tools/build_principles_visual.py`.

## Verification status

The focused persistence flow, expanded click-through crawler and 60-state
screenshot capture pass. The full suite passes: **428 passed, 9 skipped,
2 xfailed**; exact results are in `docs/ui/verification.md`. The real Snipe-IT
suite also passes: **6 passed** on 2026-11-22 against the local v8.8.3 instance.

Template/static paths and relative SQLite/document paths now resolve from the
project root, so Uvicorn can start outside the repository directory. Migration
`0003_print_attempts` was restored for legacy databases; the local database was
upgraded to `0006_maintenance_priority` without deleting its records.

## Remaining owner work

Existing business and deployment questions (rate-limit scaling, agent token
binding, maintenance status label configuration, performance measurement, and
others) remain in `docs/OPEN_QUESTIONS.md`; they were not silently resolved by
this UI recovery.
