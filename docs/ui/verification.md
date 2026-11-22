# UI recovery verification — 2026-11-22

## Phase report

| Phase | Status | Evidence |
| --- | --- | --- |
| 0 — Click-through | DONE | RED baseline committed in `docs/ui/baseline-clickthrough.txt`; final crawler: **13 pages, 252 links, 182 buttons, 257 clicks, 0 problems** (1 passed, 319.76 s). |
| 1 — Shell and errors | DONE | Canonical routes, legacy 308 redirects, shared responsive shell, complete logo and friendly HTML errors pass route, branding and browser tests. |
| 2 — Visual system | DONE | Light/dark tokens, local fonts, operation strips, mint underscores, count-up, keyboard controls, persistent filters and 15-second refresh are implemented. |
| 3 — Dashboard | DONE | Five linked tiles, attention list and two status panels; the all-passed chip has an explicit nonempty/all-passed test. |
| 4 — Handovers | DONE | Board/table, registration and case drawers work; focused browser and API tests cover creation and operation actions. |
| 5 — Maintenance | DONE | Registration, vendor send/receive, three states, costs, vendor board/table and migration 0006 pass focused browser and API tests. |
| 6 — Sync | DONE | Start/code/command/wait/result/attach flow passes through a real linked agent submission and refreshes the case passport. |
| 7 — Final verification | DONE | Full suite, screenshot/squint review and the six live Snipe-IT tests pass. |

Phases 1–6 were delivered together in commit `7c14b84`; the RED Phase 0 test was committed separately in `793331d`.

## D1–D9 closure

| Defect | Fix | Proof |
| --- | --- | --- |
| D1 — Raw API error links | HTML pages contain no `/api/...` anchors. Print/download actions use buttons, prerequisites and visible failure feedback. | Click-through crawl rejects API links, non-HTML pages and error responses. |
| D2 — Silent controls | Software override, Snipe-IT push, sign-in and other drawer controls act or are disabled with a visible reason. Copy reports success/fallback/failure. | Click-through exercises 257 clicks with no dead controls; focused sync and clipboard tests. |
| D3 — Inconsistent shell | Every page uses the same labelled desktop rail, top bar and mobile bottom nav with one active destination. | Click-through shell assertions and 60 responsive screenshots. |
| D4 — Duplicate URLs | Four canonical screens plus typed case/history routes; old routes return 308 and retain query strings. | Dashboard, characterization and click-through route tests. |
| D5 — False all-passed status | The chip requires at least one operation and every operation passed. | `test_case_board_shows_all_passed_only_when_every_operation_passed`. |
| D6 — Cropped logo | The JPEG is contained in a charcoal chip; favicon PNGs have a committed generator. | Branding tests and desktop/mobile screenshots. |
| D7 — Missing maintenance feature | Dedicated registration, three-state board, vendor workflows/table, turnaround indicators and persisted repair details. | `test_ui_flows.py`, maintenance API/repository tests and screenshots. |
| D8 — Raw HTML errors | HTML navigation errors render a friendly page with request ID and Back/Dashboard actions; APIs remain JSON. | Request-logging, error-page and click-through tests; error screenshots. |
| D9 — Weak tests/clipboard error | Click-through tests behavior rather than only HTTP 200. Clipboard tests now target `/sync` after Start sync; copy feedback was fixed. | Final click-through and clipboard browser matrix; `docs/ui/D9-clipboard.md`. |

## Screenshot inspection

`tests/e2e/test_capture_screens.py` starts the real uvicorn app against a fresh Alembic-migrated temporary SQLite database, seeds only `TEST-` records through API calls, and captures **60 screenshots**: 15 states × light/dark × desktop/mobile. All full-size captures and four 400 px squint sheets were inspected. Navigation remains visible, primary actions and statuses are legible, drawers fit at 390 px, themes are distinct, and no overlap, clipping, raw JSON, empty vendor selector or missing shell was observed.

- **Dashboard:** the five totals and attention list are the focal point; an engineer can open urgent work in two clicks.
- **Handovers board:** progress lanes are the focal point; an engineer can open a case or registration drawer in two clicks.
- **Handovers table:** sortable case rows are the focal point; an engineer can find and open a case in two clicks.
- **New handover:** the serial/registration form is the focal point; an engineer can open and submit registration in two clicks.
- **Handover case/drawer:** the operation lanes and active drawer are the focal point; an engineer can open and complete an operation in two clicks.
- **History:** the chronological event list is the focal point; an engineer can open the case and review its audit trail in two clicks.
- **Maintenance board:** repair state lanes and next-step buttons are the focal point; an engineer can send or receive a device in two clicks.
- **At vendors:** the vendor/device timing table is the focal point; an engineer can open the tab and identify overdue devices in two clicks.
- **New maintenance:** the issue/registration form is the focal point; an engineer can open and submit a repair case in two clicks.
- **Maintenance case:** the device passport and transit operations are the focal point; an engineer can open and record the next operation in two clicks.
- **Sync start/waiting:** Start sync and then the short-lived code/commands are the focal point; an engineer can obtain a device command in two clicks.
- **Sync result:** device match, hardware and software results are the focal point; an engineer can submit a report and attach it in two clicks.
- **Error page:** the one-line error and recovery actions are the focal point; an engineer can return to safe navigation in one click.

## Exact test results

- Focused persistence: `python -m pytest tests/e2e/test_ui_flows.py -q` — **1 passed** (14.60 s).
- Screenshot capture: `python -m pytest tests/e2e/test_capture_screens.py -q` — **1 passed** (55.52 s final capture).
- Click-through: `python -m pytest tests/e2e/test_clickthrough.py -q -s` — **1 passed**, 0 problems (319.76 s).
- Full suite: `python -m pytest -q` — **428 passed, 9 skipped, 2 xfailed, 2 warnings** in **592.51 s**.
- Live Snipe-IT: `python -m pytest tests/test_snipeit_live.py -m live -q` — **6 passed**.
- Final token check: `python -m pytest tests/test_brand_tokens.py tests/test_visual_quality.py -q` — **7 passed**.

Known warnings are upstream deprecation warnings for pytest-asyncio configuration, Starlette's TestClient import and Authlib's httpx integration; they are not UI failures. Live Snipe-IT tests remain skipped unless explicitly configured, and the PostgreSQL migration test remains environment-dependent.

## Real Snipe-IT data

**RUN on `fix/ui-recovery` (2026-11-22): 6 passed.** Docker Desktop and Snipe-IT v8.8.3 were available at `http://localhost:8081`; the portal health check returned `connected=true`. The live suite used the existing API token and `TEST-recipient`/`TEST-SN-0001` fixtures without printing or committing credentials.

## Open owner questions

No new questions were introduced by final verification. Relevant existing decisions remain open for oversized-file refactoring (Q-6), performance measurement (Q-7), and deployment-specific Snipe-IT maintenance labels (Q-23); the complete register is in `docs/OPEN_QUESTIONS.md`.
