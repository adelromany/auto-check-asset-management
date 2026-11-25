# Round 2 changes (owner decisions after Round 1)

Branch: stay on `feature/v2-handover-maintenance`. Rules: `docs/v2/00-README-rules-and-spec.md` section A (small reads, one step = one edit + one test, context guard, two-failure rule, UI labels short, live Snipe-IT proof, update `HANDOFF-V2.md` after each group). Put this file in `docs/v2/`.

This file WINS over `03-handover-recipient.md` and over `09-fixes-round-1.md` (group F4.5) wherever they conflict. Do ROUND 1 first if it is not finished, but apply the company rule below while you do it.

Owner decisions:
1. A company mismatch between the recipient and the device is only a WARNING. It never blocks anything. Sometimes the engineer must do it.
2. Form fields: B.tech form: after `المهندس :` put the name of the engineer responsible for the handover. Mylo form: after `توقيع مهندس الدعم الفني:` put the same. Nothing else is filled. (The owner types `{{ENGINEER}}` in those two places; nothing changes in the code plan.)
3. The handover dashboard is far too poor. Rebuild it.
4. A way to delete all app data so testing starts from zero.

---

# GROUP R1: Company mismatch becomes a warning

## R1.1 Domain and storage
- `company_conflict(device_company, recipient_company)` stays as it is (pure function). It no longer rejects anything; it only produces a warning.
- Migration `0010_round2.py`: add `recipient_company` (120, nullable) to `handovers`. Store it whenever a Snipe-IT recipient is chosen (and when a pending user is found).
- The detail and summary DTOs get `warnings: list[{code, text}]`. Add `{"code": "company_mismatch", "text": "Recipient company differs from device company"}` when `company_conflict(device_company, recipient_company)` is true. Keep the existing `company_unknown` warning as it is.
- Pure helper `case_warnings(device_company, recipient_company, ...) -> list[Warning]` in `app/domain/handover_rules.py` with a table-driven test in `tests/test_case_outcome.py`: same company none; different company one; unknown no mismatch.
- A warning NEVER changes the outcome (a case with a mismatch can still be `complete`).

## R1.2 Server behavior changes (remove the blocks)
- `POST /api/handovers/{id}/recipient` mode `snipeit`: a conflict no longer returns 422. It stores the recipient, records `RECIPIENT_CHECK` passed, writes one event `company_mismatch_warning` (device company, recipient company, engineer), and the response contains the warning.
- Checkout guard 2 from phase 03 (`company_mismatch` 422) is removed. The other guards stay (a recipient must be a Snipe-IT user; the device must not be held by someone else).
- `GET /api/snipeit/users`: `same_company` stays in the response for the UI tag only. Nothing filters by it.
- Pending-user auto-link (Round 1, F4.5): a company conflict no longer stops the link. The case is linked and carries the warning. The AUTOMATIC checkout is skipped when there is a warning (a human decides); the event `pending_user_found` says so and the case shows the chip `Check out manually`. Without a warning the rules of F4.5 are unchanged.
- Update the tests that expected 422 or no link (`grep -rn "company_mismatch" tests app`), list them in `HANDOFF-V2.md`.
Check: `pytest tests -q -k "company or recipient or checkout or pending"` green.

## R1.3 UI
- Search results: other-company users are selectable (not disabled). Show an amber `!` icon with the tag `Other company` next to the company chip.
- After choosing: the recipient card and the case header show an amber `!` chip `Company differs` with the two company names on hover or tap (title text). No dialog and no extra click.
- The Check out button stays enabled with the amber `!` shown on it.
- Handover lists and the dashboard rows show the same amber `!` for cases with the warning.
Check: Playwright: choose a Mylo user for a B.tech device; the result is selectable, the recipient is saved, the chip appears, checkout works.

## R1.4 Live proof (REQUIRED)
Update `tools/v2_probe_handover_recipient.py`: choosing `test.mylo1` for the B.tech device now PASSES with the warning; checkout to that user succeeds in Snipe-IT (verify `assigned_to`); then clean up. Update scenario S2 in `tools/v2_verify_all.py` to expect the warning and a successful checkout. Append to `docs/snipeit-integration-report.md` under "Round 2".

---

# GROUP R2: Handover dashboard rebuild (page `/`)

Problem: three tiles and a list. The owner wants a real operations dashboard that a pressured engineer reads in 5 seconds and that a manager can use to see the whole handover work. Handover data only; never maintenance numbers.

Read first: the skill-like rules in `docs/ui/DESIGN.md`, the current `templates/dashboard.html`, `static/js/dashboard*.js`, `app/services/dashboard.py`. Reference look: `docs/ui/reference-demo.html` (`grep -n "function HDash" -A 20`).

## R2.1 Data endpoint (backend first)
Extend `GET /api/dashboard/handover?period=today|7d|30d|all&company=<name|all>` (default `30d`, `all`). It returns one JSON with all blocks below. Compute with a few grouped queries (no per-case loops); all filters apply to every block.
- `tiles`: `ready` (count of Ready labs), `complete` (in period), `not_complete` (open now), `waiting_user` (open cases with `recipient_mode = pending_user`), `stalled` (open and older than `STALL_HOURS` without activity), `warnings` (open or complete cases with a company mismatch warning, in period), `avg_hours_to_complete` and `median_hours_to_complete` (created to completed, in period; null when none).
- `by_company`: for each company: `ready`, `complete`, `not_complete`, `waiting_user`.
- `ready_by_model`: Ready labs grouped by model (top 8) with company split.
- `per_day`: for the last `N` days of the period (max 30 points): `started`, `completed`.
- `missing_parts`: for open cases, count by missing operation title (top 6), for example `Signed paper 9`, `Software 4`.
- `by_engineer`: for each engineer (by `engineer_name`): `open`, `completed_in_period`.
- `attention`: up to 12 open cases needing action, sorted by priority then age: failed part, stalled, waiting user with last check time, warning. Each: `id`, `serial`, `model`, `company`, `recipient`, `reason` (short text like `Signed paper missing`, `Waiting for user 3 days`, `Software missing`), `age_hours`.
- `activity`: last 20 events across handover cases: `time`, `text` (short, like `Checked out to Ahmed Ali`, `User found: ali.hassan`, `Paper attached`), `case_id`, `serial`, `engineer`.
Tests in `tests/test_dashboard.py` with seeded cases covering every block, each period, each company filter; totals must add up (by_company sums equal the tiles).
Check: `pytest tests/test_dashboard.py -q` green.

## R2.2 Page layout (desktop 1440; phones stack in the same order)
Top bar: title **Handover**, period selector (segmented: Today, 7 days, 30 days, All), company chips (All, B.tech, Nexta, Mylo), a refresh icon, button **New handover**. Auto refresh every 30 seconds while the tab is visible.

Row 1, six KPI tiles (clickable, each loads its list in the panel at the bottom): **Ready labs**, **Complete**, **Not complete**, **Waiting for user**, **Stalled**, **Warnings**. Each tile: big number, one small label, a tiny sparkline from `per_day` where it makes sense (Complete, Not complete), and the accent colour only on the number. A tile with 0 stays calm (muted), a tile with a problem (Stalled, Warnings above 0) gets the amber or red accent.

Row 2, two wide cards:
- **Handovers per day**: bars for `started` and `completed`, last 30 days, drawn as inline SVG in JS (no chart library), with axis labels, a hover tooltip, and a legend with text. Colours: two series in the app's mint and ink tokens, both themes tested.
- **Average time to complete**: median and average in hours or days, and the percent of cases completed within 24 hours.

Row 3, three cards:
- **Ready labs**: horizontal bars by company, and under it the top models (`Latitude 5440 6`). Clicking a bar filters the list.
- **By company**: a small table (Ready, Complete, Not complete, Waiting) with the numbers as clickable cells.
- **Missing parts**: horizontal bars `Signed paper 9`, `Software 4`... (what blocks cases most). Clicking opens the cases missing that part.

Row 4, two cards:
- **Needs attention**: the `attention` list with the reason text and one button per row (**Continue**, **Check now** for waiting users). This is the most important card; give it the most visual weight.
- **Recent activity**: a vertical feed with time ago, short text, serial in mono, engineer name; clicking opens the case.

Row 5: **By engineer** table (Open now, Completed in period) with a small bar in the cell.

Bottom: the list panel (the one that exists) showing the cases of whichever tile, bar or cell was clicked, with a title and a **Clear** button. Default: Needs attention.

Rules:
- Short labels only; no explanatory sentences anywhere.
- Empty data: tiles show `0`, charts show a flat baseline with the label `No data`, lists show a dash. The page must look intentional with NO data (the owner starts from zero) and with 200 cases.
- Every number and bar is clickable or has a visible reason why not. Keyboard accessible.
- Use the `dataviz` approach: text labels on every mark, colour never the only carrier of meaning, palette from tokens, light and dark verified.
- No new libraries. Charts are small functions in `static/js/dashboard_charts.js`. Page script `static/js/dashboard.js`. Strict CSP. Rebuild CSS with `npm run build:css`.
- Performance: one request per refresh; render under 100 ms for 200 cases.

## R2.3 Demo data tool (optional, removable)
`tools/seed_demo_handovers.py [--count 60] [--remove]`: inserts clearly marked demo cases into the PORTAL database only (serial prefix `DEMO-`, three companies, all outcomes, waiting users, stalled, warnings, events over the last 30 days, engineers `Demo Engineer 1..3`) so the dashboard can be judged with realistic numbers. `--remove` deletes exactly those rows (by the `DEMO-` prefix) and nothing else. It never talks to Snipe-IT. It refuses to run when `APP_ENV=production`.
Check: seed 60; open `/`; screenshots; `--remove`; counts return to the previous values.

## R2.4 Tests and visual check
- Playwright: seed with the demo tool, open `/`, assert six tiles, both charts have marks, the attention list has rows, clicking a tile fills the bottom list, period and company filters change the numbers, no horizontal scroll at 390 and 1440 px, both themes. Empty database test: all six tiles show 0, no JS error in the console, no broken layout.
- Screenshots to `docs/review/v2/dashboard-*.png` (empty and full, light and dark, desktop and phone).
Check: e2e folder green.

## R2.5 Commit and update `HANDOFF-V2.md`.

---

# GROUP R3: Reset app data (start testing from zero)

Goal: delete every record the portal created (cases, stages, events, maintenance info, agent sessions, uploaded or generated files) so the owner can test from an empty portal. Never touch Snipe-IT. Keep configuration and reference data (vendors list is configuration: keep it by default).

## R3.1 Tool `tools/reset_app_data.py`
Behavior:
1. Reads `DATABASE_URL` from the environment (same as the app). Refuses when `APP_ENV=production` unless `--i-know-this-is-production` is also given.
2. Default is a DRY RUN: prints each table and its row count that would be deleted, and the folder(s) with uploaded files and their file counts. Deletes nothing.
3. With `--yes`: first makes a backup (SQLite: copy the db file to `data/backup-YYYYmmdd-HHMMSS.db`; PostgreSQL: print that the owner must back up and require the flag `--no-backup` to continue), then deletes rows in dependency order inside one transaction, then removes the uploaded files folder content (only inside the configured upload dir; refuse any path outside the project), then prints the counts after (all zero).
4. Tables to clear: handover stages, handover events, handovers (both kinds), maintenance info, and any session or report storage tables. Tables to KEEP: alembic version, diagnosis categories (reasons), maintenance destinations (vendors), any user or role cache. Flag `--vendors` also clears vendors. Find the real table names from the models (`grep -n "__tablename__" app/db/models/*.py`) and list them in `HANDOFF-V2.md`; do not guess.
5. Flag `--demo-only` deletes only rows with the `DEMO-` serial prefix (same as the demo tool `--remove`).
6. Never deletes the migrations table and never drops tables.
Tests `tests/test_reset_app_data.py` on a temporary SQLite database: dry run changes nothing; `--yes` clears the right tables and keeps reasons and vendors; the backup file exists; a path outside the upload dir is refused; production guard works.
Check: `pytest tests/test_reset_app_data.py -q` green.

## R3.2 Run it for the owner (document, do not run on the owner's real data without asking)
In `README` section "V2" add the exact commands: dry run, then `--yes`. In `HANDOFF-V2.md` write: `Reset command: python tools/reset_app_data.py --yes (backup is created first)`.
Do NOT run `--yes` yourself on the owner's database. Run only the dry run and show the counts in `HANDOFF-V2.md`.

## R3.3 Optional button
Do NOT add a delete-all button to the UI.

---

# GROUP R4: Final check of Round 2
1. Full pytest, `ruff`, architecture test.
2. Live scenarios in `tools/v2_verify_all.py`: update S2 (warning and successful checkout), keep the others; save results to `docs/v2-verification.md` under "Round 2".
3. Update `docs/OPEN_QUESTIONS.md`: company mismatch is a warning only; owner confirmed the form positions (B.tech after `المهندس :`, Mylo after `توقيع مهندس الدعم الفني:`).
4. Commit and push. Final message to the owner: commit id, scenarios passed, screenshot folder, the reset command, and the owner actions still open (templates saved as `.docx` with `{{ENGINEER}}` in `forms/`; Nexta template; confirm the Mylo form company name).

If you reach about 25 tool calls in one chat, write the state into `HANDOFF-V2.md` and stop; the owner will start a new chat with the START MESSAGE from `00-README` plus the line: `Continue ROUND 2 from docs/v2/10-fixes-round-2.md`.
