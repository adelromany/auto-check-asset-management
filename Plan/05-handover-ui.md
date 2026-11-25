# Phase 05: Handover UI (workspace and dashboard)

Prerequisite: `HANDOFF-V2.md` says `PHASE 04 DONE`. Read `00-README` A (rules 3, 10, 11) and B1.

Goal: the screens for the Handover section. Backend is done; this phase only calls it. Follow the existing UI conventions: tokens and components in `styles/app.css` and `docs/ui/DESIGN.md`, partials in `templates/partials/`, one JS file per page in `static/js/` (strict CSP: no inline script or style), rebuild CSS with `npm run build:css` after class changes. Never edit `static/css/app.css` by hand.

Reference look: `docs/ui/reference-demo.html`. Read one part at a time, for example `grep -n "function Workspace" -A 14 docs/ui/reference-demo.html`, `grep -n "function devPanel"`, `grep -n "function recPanel"`, `grep -n "function hoPanel"`, `grep -n "function HDash"`. Copy the structure and class ideas, not the code.

## Step 5.1 Navigation and routes
- Left rail (and bottom bar on phones) has two labeled groups: **Handover** (Dashboard `/`, Handovers `/handovers`) and **Maintenance** (Dashboard `/maintenance`, Devices `/maintenance/devices`). Remove "Sync" from the nav; keep the `/sync` route alive (the device check uses it inside the case).
- Case page: `/handovers/{id}`. History page stays `/handovers/{id}/history`.
- Update the nav partials (`templates/partials/rail.html`, `bottom_nav.html`) and the crawler/click-through test expectations in `tests/e2e/` (labels and active item).
Check: `pytest tests/e2e -q -k nav` (or the nearest existing nav test) green.

## Step 5.2 Handover dashboard (`/`)
Page title "Handover". Three large tiles, then a list area:
1. **Ready labs** (number) with a row of company chips under it (`B.tech 4`, `Mylo 2`, ...) from `GET /api/dashboard/handover`.
2. **Complete** (number).
3. **Not complete yet** (number).
Clicking a tile (or a company chip) loads the matching cases below with `GET /api/handovers?outcome=...&company=...`. Each row: serial (mono), model, company chip, recipient or "No recipient", the missing parts (short titles, max 3 then "+n"), age, and one button: **Continue** (Not complete and Ready) or **Open** (Complete). Empty list: one dash. A "New handover" button top right.
No explanatory sentences anywhere.
Check: add a Playwright test: seed 3 cases (Ready B.tech, Complete Mylo, Not complete B.tech), open `/`, click each tile, assert the rows appear, click Continue and land on `/handovers/{id}`.

## Step 5.3 New handover
"New handover" opens a drawer: one field "Serial". As the engineer types, nothing is created; Enter or the **Start** button calls `POST /api/handovers`. Success goes to `/handovers/{id}`. The errors from phase 02 (`Serial not found in Snipe-IT`, an active case already exists with a link "Open") show as one plain line under the field.
Check: Playwright: unknown serial shows the line; known serial opens the case page.

## Step 5.4 Case page = three panels (`/handovers/{id}`)
Header: serial (mono), model, company chip, the outcome pill (**Complete** / **Not complete yet** / **Ready**), History button. Below, three panels side by side (stack on narrow screens):

**Panel 1 Device**
- Snipe-IT status chip + a select of status labels (from `GET /api/snipeit/status-labels`) with button **Apply**; the chip turns green when it equals "Ready to deploy".
- Company chip.
- **Check device**: starts the existing code flow (reuse the logic in `static/js/sync.js` and the endpoints it uses): shows the short code, the one-line command with a **Copy** button (clipboard code already exists in `static/js/clipboard.js`), and a small waiting ring. When the report arrives the hardware/software list appears (ticks and crosses). Missing software offers **Check again**; accepting a gap uses the existing not-done reason flow.

**Panel 2 Recipient**
- Search box (calls `GET /api/snipeit/users?q=...&handover_id=...`, min 2 chars). Each result: name, email, company chip. Results with `same_company === false` are disabled with the tag "Other company".
- Two links under the box: **None for now** and **Not in Snipe-IT yet** (the second shows name + email fields and Save).
- After choosing: card with name, email, company; **Change**.
- **Current items** list from `/recipient/items`: each with a checkbox "Take back"; button **Take back selected** then **Continue** (calls the confirm endpoint). Empty: "None".

**Panel 3 Handover**
- Engineer (read-only, from the SSO session).
- **Print form** button: downloads the docx (`GET /form`); a failure shows the one-line error (for example `No form template for Nexta`).
- **Signed paper**: drop zone / file button; on upload calls `POST /signed-paper`; shows two ticks (Saved, Attached to Snipe-IT) and **Retry** on the failed one only.
- **Check out** button: enabled when the recipient is a Snipe-IT user; if disabled show the reason as a tag ("Choose a recipient").
- Bottom: the outcome pill and the list of `missing` parts as short chips.

Behavior rules:
- Every button either works and shows a result (toast or state change) or is disabled with a visible reason. No silent buttons.
- Every part updates from the server response (`HandoverDetail`), no local guessing.
- Progress feedback: a ring while waiting, a small check animation when a part passes. Respect `prefers-reduced-motion`.
- Parts are independent: the engineer may do them in any order.
Check: Playwright click-through of the whole page with the fake Snipe-IT client: apply status, search, mismatch disabled, choose recipient, take back, print (download event), upload, checkout, outcome becomes Complete.

## Step 5.5 Handovers list (`/handovers`)
Table with filters (company, outcome, search by serial or recipient). Same row format as the dashboard list. Row click opens the case. Keep keyboard focus order sane.
Check: Playwright: filter by company shows only that company's rows.

## Step 5.6 Visual review (a text-only model must still do this)
Run the screenshot helper the repo already has (`tests/e2e` capture tests or `tools/`), then check programmatically: no horizontal scroll at 390 px and 1440 px (`document.documentElement.scrollWidth <= innerWidth`), no element with `overflow` clipping text, contrast tokens unchanged, both themes render. If you can view images, look at them; if you cannot, say so in `HANDOFF-V2.md` and ask the owner to review `docs/review/` screenshots.
Check: the full e2e folder green.

## Step 5.7 Close the phase
Full suite once. `HANDOFF-V2.md`: `PHASE 05 DONE`. Commit.
Next file: `06-maintenance-backend.md`.
