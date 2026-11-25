# Phase 07: Maintenance UI (devices screen and dashboard)

Prerequisite: `HANDOFF-V2.md` says `PHASE 06 DONE`. Read `00-README` A (rules 3, 10, 11) and B2. Same UI conventions as phase 05 (tokens, partials, one JS file per page, strict CSP, `npm run build:css`).

Reference look: `docs/ui/reference-demo.html` (maintenance parts). Use `grep -n "function Maint" -A 14 docs/ui/reference-demo.html`. Copy structure, not code.

## Step 7.1 Routes
- `/maintenance` = Maintenance dashboard.
- `/maintenance/devices` = Devices screen (add, send, receive).
- `/maintenance/{id}` stays the case page (detail and history).
Add the page routes in `app/routers/pages.py` (follow the existing pattern) and templates `templates/maintenance_devices.html`; JS `static/js/maintenance_devices.js`.
Check: `pytest tests/e2e -q -k "maintenance and nav"` (or the nearest) green.

## Step 7.2 Add device card (top of Devices screen)
Fields and buttons, short labels only:
1. Field **Serial**. After typing (debounce 400 ms, min 3 chars) call `GET /api/maintenance/device-lookup`; show a small card: model, company chip, Snipe-IT status chip, current user or "No user". Unknown serial: one plain line `Not found`.
2. Select **Reason** (from `GET /api/maintenance/reasons`). Choosing `Other` reveals a text field **Details** (required, max 300).
3. Optional select **Vendor** (planned). Default empty.
4. Buttons: **Add** (creates the case, `POST /api/maintenance/cases`), then on the new row two buttons: **Set Maintenance** and **Remove from user** (the second is shown only when the device has a user). Each shows a result chip (done or the one-line error) and updates the row from the server response.
Behavior: after **Add** the card clears and focuses Serial again (engineers add many devices in a row). Enter in Serial moves to Reason.
Check: Playwright: lookup shows company; Other requires text; Add creates a row; Set Maintenance flips the chip; Remove from user removes the user.

## Step 7.3 Two tables (tabs: With IT | At vendor)
- **With IT** table: checkbox, serial, model, company chip, reason, days, planned vendor, row buttons (the two from 7.2 when not done). A sticky bar appears when at least one row is checked: **Send batch (n)**.
- **At vendor** table: checkbox, serial, model, company, vendor, sent date, days, reason. Sticky bar: **Receive batch (n)**.
- Filters above both tables: company, model, vendor (selects), search by serial.
Check: Playwright: filters work; the sticky bar shows the right count.

## Step 7.4 Send batch drawer
Opens from **Send batch (n)**: select **Vendor** (with a small "+ New vendor" inline field), date field **Day** (default today), button **Send**. After the response: a result list per device (✓ or the one-line error); successful ones leave the With IT table; failed ones stay checked.
Check: Playwright: send two devices; both appear in At vendor; a forced error stays in With IT.

## Step 7.5 Receive batch drawer
From **Receive batch (n)**: date field **Date** (default today), button **Receive**. Result list per device with two ticks (Returned, Status Ready); a failed status shows **Retry** on that device only (calls `/ready-status`). Received devices leave the At vendor table.
Check: Playwright: receive one of two; the other stays; the status tick is shown.

## Step 7.6 Maintenance dashboard (`/maintenance`)
Page title "Maintenance". Data from `GET /api/dashboard/maintenance`.
1. Two big tiles: **Needs maintenance** (number) and **In maintenance** (number) with the average days under the second.
2. Under each tile three grouped lists, as horizontal bars with the count (no chart library): **By model**, **By company**, **By vendor** (`Not assigned` for no vendor). Clicking a bar filters the device table below.
3. Table **Devices in maintenance**: serial, model, company, vendor, **Days** (a coloured chip: normal, amber above 7 days, red above 14 days; thresholds in `app/config.py` as `MAINT_WARN_DAYS=7`, `MAINT_LATE_DAYS=14`), reason. Sorted by days descending.
4. No handover numbers anywhere on this page.
Use the existing `dataviz` look of the app tokens; bars must have text labels (not colour only).
Check: Playwright: seed cases; tiles show the numbers; clicking a company bar filters the table; sorting by days.

## Step 7.7 Case page (`/maintenance/{id}`)
Keep it small: header (serial, model, company, state chip), the seven parts as a vertical list with state, the reason, vendor, dates, days; buttons only where an action exists (Set Maintenance, Remove from user, Retry status). History link.
Check: Playwright: open a case from the dashboard table.

## Step 7.8 Visual check
Same as step 5.6 (no horizontal scroll at 390 and 1440 px, both themes, every button works or is disabled with a visible reason).
Check: the full e2e folder green.

## Step 7.9 Close the phase
Full suite once. `HANDOFF-V2.md`: `PHASE 07 DONE`. Commit.
Next file: `08-final-verification.md`.
