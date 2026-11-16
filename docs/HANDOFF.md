# HANDOFF — five-part owner review (A → E)

Base: `origin/docs/deployment-guide` @ `78fdb96`.
Branches, stacked: A `refactor/independent-operations` → B `feature/screens-split` →
C `feature/case-board-ui` → D `feature/maintenance-cases` → E `docs/ui-sync`.

## Baseline (step 1, inspected, no code changes)
- Suite: `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py`
  → **363 passed, 1 failed, 7 skipped** in 38.68 s. The one failure,
  `test_agent_flow_with_mismatched_serial_fails_stage_three`, passes in
  isolation (order-dependent shared state); recorded as a baseline flake.
- Visible word count (test client, tags stripped): `/handovers` = **105**,
  case page `/handovers/{id}` = **332**.
- Confirmed: `can_run` blocks on `STAGE_DEPENDENCIES` (409 "Waiting for …");
  any failed/blocked → case `stalled`; `record_agent_report` couples software
  and recipient; `/` is the agent page; `/handovers` is dashboard + creation
  form; no maintenance concept; one active case per serial via partial index.
- Brand: `static/img/b_labs.jpeg` = white `b_labs` wordmark on charcoal with a
  teal underscore. Accent = teal, neutral = charcoal.

step done: 1 inspection + HANDOFF created; next: A1/A2 domain rule + statuses; tests: 363 passed, 1 failed (order-dependent), 7 skipped

## Part A — independent operations (branch `refactor/independent-operations`)
- A1/A2 domain contract: `app/domain/catalog.py` adds `CaseKind` and the
  operation catalog; `Operation`/`Stage` alias; statuses `pending`, `passed`,
  `failed`, `not_done`; `RECOMMENDED_AFTER` is advice only; `advice()` and
  `performed_before()` replace the blocking `can_run`.
- A3/A4 service + schema: one outcome and one `operation_recorded` event per
  operation, `not_done` with mandatory reason, retry, close with gaps (literal
  `CLOSE`), reopen, independent hardware/software agent evaluation, in-process
  lock per case+operation and conditional `UPDATE`. Migration
  `0003_independent_operations` remaps `skipped→not_done`, `blocked→failed`,
  `stalled→in_progress`, adds `kind`/`closed_gaps`/recipient name+email and
  rebuilds the active-serial index; downgrade reverses it.
- A5/A6 API + tests: `/active`, `not-done`, `retry`, `close`, `reopen`;
  `kind`/`q` filters; `InputMissing` → 422. Close/reopen and 0003 up/down are
  covered by tests.
- Docs: BIZ-06/08/09/14/18 rewritten, BIZ-19/20 added; D-68 implemented,
  D-69/D-70/D-71 proposed; Q-16…Q-20 opened; LIVE GRAPH and generated visual
  pages regenerated.
- Tests: `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py`
  → **358 passed, 7 skipped**.
- Also fixed an undefined `snipeithandover_http_error` reference in the
  handover router (now `snipeit_http_error`).

## Part B — separate screens (branch `feature/screens-split`)
- `/` is Dashboard (read-only overview, search, KPI tiles, charts), `/new` is Registration, `/cases` is Cases list, `/cases/{id}` is Case board, `/cases/{id}/history` is History, `/device-check` is Device check.
- `GET /?handover_id=` redirects (307) to `/device-check?handover_id=`.
- `GET /` with SSO off answers 200, characterization tests green.
- Branding: `b_labs.jpeg` logo in `partials/logo.html`, `Handover Portal` title in `app/config.py` and `app/main.py`, favicon updated, monitor SVG and old title removed, `tests/test_branding.py` passes.
- Tests: 369 passed, 7 skipped.

## Part C — calm case board UI (branch `feature/case-board-ui`)
- Design doc `docs/ui/DESIGN.md` (364 words, <400 budget) defining surface `#1A1A1A`, mint accent `#71E3D9`, 3-zone layout (Sticky Passport, 3-lane Board, Side-sheet Drawer), day-grouped history.
- Shell components: left rail (`partials/rail.html`) with mint active tab, mobile bottom nav (`partials/bottom_nav.html`), topbar with omnibox search (`partials/topbar.html`).
- Centered calm registration card in `templates/new_case.html` (<80 words).
- 3-zone case board in `templates/handover_detail.html` (Passport with SVG progress ring, 3 lanes with 10 operation tiles, hidden side-sheet drawer).
- Side-sheet operation drawer in `static/js/handover_detail.js` with keyboard navigation, Esc/backdrop dismissal, reason chips, retry, and software override.
- Day-grouped history timeline in `templates/case_history.html` with 2s event coalescing, human-readable sentences, and collapsible JSON disclosure.
- Word budgets strictly met: Desktop board <=220, Dashboard <=160, Registration <=80, Mobile 390px <=80.
- Visual review screenshots captured at 1440x900 and 390x844 (light & dark).
- Tests: 377 passed, 7 skipped.
- step done: b2e01b4 feat(branding): use b_labs logo, Handover Portal name, and split dashboard and device-check routes; next: Part C complete redesign; tests: 369 passed, 7 skipped

## Part C — calm case board (branch `feature/case-board-ui`)
- Brand tokens: `b_labs` teal accent on charcoal neutrals in light and dark.
- Initial case board pass.
