# 14: Owner fixes on top of commit 92f0679 (supersedes 09 to 13)

Base: commit `92f0679` ("pre prod") on `feature/v2-handover-maintenance`. This file replaces `09`, `10`, `11`, `12` and `13`. Do not open them. Everything you need is here.

How to read: it has PARTs. Read only the part you work on: `grep -n "^## PART" docs/v2/14-polish-from-92f0679.md`, then `sed -n <start>,<end>p`. Never read the whole file at once.

## PART 0 Rules and baseline (always read)
1. ONE model at a time. Write `WORKING: PART <n> <date time>` in `HANDOFF-V2.md`; if such a line is younger than 2 hours, STOP and tell the owner. On finish or stop write `IDLE`.
2. One step = one small edit + one test + one short commit (`part<n> step<m>: ...`). Max 3 files per step. Never rewrite a whole file. Never delete a test to get green (change a test only when this file changes the rule; list each in `HANDOFF-V2.md`).
3. Context guard: after about 25 tool calls write the state into `HANDOFF-V2.md` (part, step, what passes, what fails) and STOP. The owner opens a new chat with the START MESSAGE of `docs/v2/00-README-rules-and-spec.md` plus: `Continue file 14 at PART <n>`.
4. Two-failure rule: the same test fails twice after your fixes: STOP, write the failure down, do not loop.
5. Layering stays: routers, services, repositories/clients, db; `app/domain` pure. Strict CSP; no inline script or style. `npm run build:css` after class changes; never edit `static/css/app.css` by hand. UI text = short labels only; no explanatory sentences.
6. Snipe-IT: live proof for every Snipe-IT feature against the dev stack, `TEST-` data only, never print the token. When you add a module or change dependencies, update the LIVE GRAPH rows and regenerate `docs/principles/visual/*` (the previous rounds needed this; `tests/test_graph_consistency.py` tells you).
7. A part ends with: focused tests green, then the full suite once, `ruff check .`, `HANDOFF-V2.md` gets `PART <n> DONE <commit id>`, lock becomes `IDLE`.
8. Test hangs: `HANDOFF-V2.md` at this commit notes an API-test fixture that stalled. Always run pytest with a timeout, for example `timeout 600 pytest <files> -q -x -p no:cacheprovider`. Never run the whole suite more than once per part.

### Baseline (do first, change nothing)
0.1 `git switch -c feature/v2-polish 92f0679` (new branch; do not touch the old one). `git status --short` must be clean except the owner's untracked files (`.env`, `error*.png`, `Plan*`, root `B.tech.docx`/`Mylo.docx`); do not delete them.
0.2 `alembic heads` (expect `0012_vendor_contacts`). Use a THROW-AWAY database for migration checks.
0.3 Run: `timeout 900 pytest -q -p no:cacheprovider --deselect tests/test_clipboard_playwright.py -x --maxfail=5` in chunks if it stalls (`tests/test_domain_rules.py tests/test_case_outcome.py`, then `tests/test_handovers_api.py`, `tests/test_maintenance_api.py tests/test_maintenance_state.py`, `tests/test_dashboard.py`, `tests/test_documents.py tests/test_form_fill.py tests/test_forms_service.py`). Write the baseline result (passed, failed names, hangs) in `HANDOFF-V2.md` as `BASELINE`. Pre-existing failures are not yours; report them, do not hide them.
0.4 Check the dev Snipe-IT: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/login` = 200; `python tools/snipeit_probe.py` all PASS. If the stack is down, start it as `deploy/snipeit-dev/README.md` says.
0.5 Commit `HANDOFF-V2.md`. Lock `IDLE`.

Owner requests handled below:
- PART 1: only three states everywhere in Handover (Ready lab, Complete, Not complete).
- PART 2: choose the TYPE at the start; requirements change with the type.
- PART 3: show the device's current Snipe-IT status and holder clearly; Check in naming.
- PART 4: Check out always clickable when a recipient exists.
- PART 5: fill hardware into the form; Print really prints.
- PART 6: cancel and delete; an open case must never lock the device.
- PART 7: Devices page with a vertical history.
- PART 8: user not yet in Snipe-IT: code + username, daily check, auto-link.
- PART 9: final verification.

---

## PART 1 Three states only
Owner: "there are 3 states only: Ready labs, Complete, Not complete".

1.1 Find every visible state word: `grep -rn "Stalled\|stalled\|Draft\|In progress\|Closed with gaps\|Waiting for user\|waiting_user\|Warnings" templates static/js | cut -c1-120`.
1.2 Dashboard (`templates/dashboard.html`, `static/js/dashboard.js`): keep exactly THREE tiles: **Ready labs**, **Complete**, **Not complete**. Remove the tiles Waiting for user, Stalled, Warnings (keep the backend fields; they feed small chips, see 1.3). The grid becomes 3 columns (stacks on phone). Keep the other cards (per day, time to complete, by company, missing parts, needs attention, recent activity, by engineer).
1.3 Rows and lists: the state shown in a row is only one of the three words. Extra facts appear as small neutral chips next to the row, not as states: `Waiting user`, `Company differs !`, `Stale` (older than `STALL_HOURS`). Cancelled cases are hidden from every list and tile by default.
1.4 Handovers list (`templates/handovers.html`, `static/js/handovers.js`): the state filter has exactly: All, Ready lab, Complete, Not complete. Remove the other options (draft, in progress, stalled, closed with gaps). The query parameter `status` is mapped to `outcome` server-side if old links use it.
1.5 Case header pill shows one of the three (it already does; verify). Internal statuses (`draft`, `in_progress`, `stalled`...) may stay in the database but never in the UI.
1.6 Update tests that assert the removed tiles or filter options (`tests/test_phase05_ui.py`, `tests/test_dashboard.py`, e2e). Add a Playwright test: dashboard has exactly three tiles; the state filter has exactly four options.
Check: focused tests green; screenshot `docs/review/v2/p1-dashboard.png`.

---

## PART 2 Type chosen at the start; requirements follow the type
Owner: when starting a handover there is no choice of type, and the requirements do not change with the type. The three types are:
- **Lab only**: prepare a device, no user yet. Needs: Device status = Ready to deploy, device check (agent report), software check. When these pass the case is a **Ready lab**. Nothing about recipient, paper or checkout is required or shown.
- **Lab + user**: the user exists in Snipe-IT. Needs all nine parts: Device status, Agent report, Software check, Form, Recipient, Recipient items, Check out, Signed scan, Attached to Snipe-IT. When all pass: **Complete**.
- **User not ready**: the user is not in Snipe-IT yet. Needs the same nine parts, but Recipient, Recipient items and Check out wait until the user is linked (PART 8). Until then the case is **Not complete**; the signed scan is still uploaded to the DEVICE in Snipe-IT.

2.1 Domain (pure, `app/domain/handover_rules.py`):
- Store the type in the existing column `recipient_mode`: `none` = Lab only, `snipeit` = Lab + user, `pending_user` = User not ready (the old value `not_in_snipeit` is treated as `pending_user`; migrate rows in 2.2). A case with no value yet is treated as `snipeit` until the engineer picks.
- `required_operations(mode) -> tuple[Operation, ...]`: `none` gives DEVICE_STATUS, AGENT_REPORT, SOFTWARE_CHECK; `snipeit` and `pending_user` give all nine.
- `case_outcome(states, mode, cancelled)` and `missing_parts(states, mode)` use `required_operations`. Outcome: all required passed and mode `none` = `ready`; all required passed otherwise = `complete`; else `not_complete`. Warnings never change the outcome.
- `kind_label(mode)`: `Lab only`, `Lab + user`, `User not ready`.
Tests in `tests/test_case_outcome.py`: table-driven for the three modes, including a lab with the three parts passed (ready), a lab+user with one missing (not complete), and `pending_user` with everything but the recipient parts (not complete) and then all passed (complete).

2.2 Migration `0013_case_type.py` (parent `0012_vendor_contacts`; check `alembic heads`): data step `UPDATE handovers SET recipient_mode='pending_user' WHERE recipient_mode='not_in_snipeit'`. No new columns here. Test upgrade, downgrade, upgrade on a throw-away database.

2.3 Server:
- `POST /api/handovers` accepts `mode` (`none|snipeit|pending_user`, default `snipeit`) and stores it.
- `POST /api/handovers/{id}/mode` body `{"mode": ...}` changes the type while the case is open. Rule: changing to `none` is refused with `The device is already checked out` when CHECKOUT passed. Changing never deletes recorded parts. Event `mode_changed`.
- The existing recipient endpoint keeps working; choosing a Snipe-IT recipient sets mode `snipeit` automatically; the buttons "None" / "Not in Snipe-IT" of the old UI are removed (the type chooser replaces them).
- DTOs: `mode`, `kind_label`, `required` (list of operation keys) so the UI never guesses.
Tests: create with each mode; change mode; refused change; DTO has `required`.

2.4 UI:
- **New handover drawer**: Serial field, then (after the device lookup card, PART 3) three large buttons with an icon each: **Lab only**, **Lab + user**, **User not ready**. Start is disabled until one is chosen.
- **Case page**: a segmented control under the header with the same three; changing it calls `/mode` and re-renders from the response. The page shows ONLY the panels needed: Lab only = Device panel; Lab + user = Device, Recipient, Handover; User not ready = Device, a Waiting-user card (PART 8) and Handover with the scan upload. Hidden parts do not appear in `missing`.
- The outcome pill shows Ready lab, Complete or Not complete yet.
Playwright: start each type; check which panels show; switch type; a Lab only case with three parts passed shows Ready lab.

2.5 Live check: scenario in `tools/v2_verify_all.py` (or a new `tools/v2_probe_types.py`): `TEST-SN-0002` as Lab only becomes `ready` after device status + agent report + software; the same case switched to Lab + user then needs the recipient parts (outcome `not_complete`), completes after recipient + checkout + scan (Snipe-IT shows the user and the file).
Close the part.

---

## PART 3 Device status and holder, clear, and "Check in"
Owner: show clearly the device's current status on the asset and whether it is with a user; the button must be called Check in, not Take back.

3.1 Backend: `GET /api/handovers/{id}/device-live` reads the asset from Snipe-IT NOW and returns `{status, status_id, deployable, asset_tag, model, company, assigned_to: {id, name, email, username, company} | null}` (fetch the assignee with `get_user` only when assigned; if Snipe-IT is down return 503 with a one-line message). Reuse the existing lookup code; one implementation only. Also store the holder name on the case (new nullable columns `device_holder_id`, `device_holder_name` in migration `0014_device_holder.py`) every time the case reads the device, so lists can show it without a live call.
3.2 `POST /api/handovers/{id}/device/checkin` checks the device in from its current holder (existing `checkin_asset`), re-reads the asset, refreshes the stored status and holder, writes an event `device_checked_in` (holder name). If the device is not assigned: 200 with `{"changed": false}`.
3.3 Serial lookup before starting (drawer): reuse `GET /api/snipeit/device-lookup?serial=` (exists at `app/routers/snipeit.py`); make sure it returns the same fields as 3.1 plus a `multiple` flag with candidates when the serial matches more than one asset. The drawer shows the card (model, company chip, status chip, `With: <name>` or `Not assigned`). If an active handover case already exists for this serial, show `Open case` link instead of failing later.
3.4 UI, Device panel top block (big, impossible to miss):
- Status chip with colour: green for Ready to deploy, amber for other deployable states, red for undeployable (Maintenance...).
- Line: `With: <name> (<company>)` or `Not assigned`.
- Button **Check in** (only when assigned). Button **Refresh** (calls device-live). Small text `Updated <time>`.
- The status select and **Apply** stay below.
- Refresh runs automatically when the case page opens and every time Apply or Check in finishes.
3.5 Rename in the UI: every "Take back", "Take back selected" becomes **Check in**; the title "Current items" becomes **Other devices with this user**. When the recipient has no other devices show one muted line `None` and nothing else (no buttons). When there are devices: a checkbox list, buttons **Check in** (for ticked rows) and **Keep all**; after either the list shows `Checked in` / `Kept` and the buttons disappear. `grep -rn "Take back\|Current items" templates static app tests` and fix every hit, including tests.
Tests: device-live with assigned and free asset (fake client); device/checkin; Playwright: holder shows and Check in clears it; label text assertions.
Live proof: `TEST-SN-0005` is held by `test.btech2`: device-live shows him; `device/checkin` frees it in Snipe-IT (read back); re-seed afterwards. Append to `docs/snipeit-integration-report.md` under "Polish".
Close the part.

---

## PART 4 Check out is always clickable when a recipient exists
Owner: the Check out button must be clickable in all cases as long as a recipient is available. In the owner's screenshot it was faded because the checkout part had already passed.

4.1 UI (`static/js/handover-case.js`): the button is enabled whenever `mode === "snipeit"` and a Snipe-IT recipient id exists, whatever the other parts and even when CHECKOUT already passed. It is disabled only when there is no Snipe-IT recipient, with the visible reason chip `Choose a recipient`. When CHECKOUT passed show a line `✓ Checked out to <name>` and rename the button **Check out again**. Remove the `checkoutStage.status === "passed"` disable.
4.2 Server (`app/services/snipeit_ops.py`, `POST /{id}/checkout`, optional body `{"replace_holder": bool}`):
- No Snipe-IT recipient: 422 `Choose a Snipe-IT recipient first`.
- Device already with the same recipient: 200, record CHECKOUT passed, detail `{"already": true}`.
- Device with another user: without `replace_holder` return 409 `{"code": "held_by_other", "holder": "<name>"}`; with `replace_holder=true` check it in first, then check it out (two events).
- Not assigned: check out and set the Deployed status as today.
- Company difference stays a warning only (no block).
4.3 UI for the 409: under the button show `Held by <name>` and a second button **Check in and check out** which repeats the request with `replace_holder=true`.
Tests (fake client): each branch above; Playwright: button enabled with a recipient and a passed checkout; same-user click is a no-op success; other-holder shows the second button and works.
Live proof (TEST data): device with `test.btech1`, check out to `test.btech2` with replace; Snipe-IT shows `test.btech2`; same user again returns already; clean up.
Close the part.

---

## PART 5 Form: fill hardware; Print really prints
Owner: fill the hardware information in both forms (B.tech and Mylo have cells for hard disk, RAM, processor); Print must print, not download.

Facts about the templates in `forms/` (verified): both contain `{{ENGINEER}}` after the engineer label (already filled by `fill_engineer`).
- `Mylo.docx`: table 1 has a header row `NO. | SPECIFICATION | BRAND / TYPE | CONFIG.` and rows `01 Processor I5 (empty)`, `02 RAM 8 (empty)`; table 0 has rows `Model | (empty)` and `Serial | (empty)`.
- `B.tech.docx`: one table with the same header and rows `01 Processor`, `02 RAM`, ... `07 Hard Disk`, ... all with an empty CONFIG. cell. Other rows (VGA, Sound...) are NOT filled by us.
The agent report fields available: `serial`, `hostname`, `manufacturer`, `model`, `cpu`, `cpu_cores`, `ram_gb`, `os_name`, `os_version`, `os_arch`, `disks[] {name, size_gb, type}`, `windows_activation`, `software_checks[]`.

5.1 Pure function `app/domain/form_fill.py`: add `fill_form(docx_bytes, *, engineer, hardware: dict) -> bytes` (keep `fill_engineer` working). `hardware` keys: `processor`, `ram`, `disk`, `model`, `serial` (all optional strings). Rules, using `zipfile` + `re` only:
- Work on `word/document.xml`. For each table row (`<w:tr>`) read the text of its cells. If a row has a cell whose text (trimmed, case-insensitive) is `Processor`, `RAM` or `Hard Disk`, put the value in the LAST cell of that row (the CONFIG. cell). For tables whose first column is `Model` or `Serial` (two-cell rows), put the value in the second cell.
- Writing into an empty cell: the cell's paragraph has no `<w:t>`; insert `<w:r><w:rPr>(copy the paragraph's `<w:pPr><w:rPr>` content if it exists)</w:rPr><w:t xml:space="preserve">VALUE</w:t></w:r>` before `</w:p>`. If the cell already has text runs, replace the text of the first run and empty the rest (same split-run logic as the placeholder). Escape XML. Do not change cell widths or any other part of the XML.
- A missing value leaves the cell empty. Never write placeholder text like `N/A`. The rows `BRAND / TYPE` stay as in the template.
- Values: processor = `cpu` (trim; add ` (<n> cores)` only if `cpu_cores` exists); ram = `<ram_gb> GB` (round to the nearest integer); disk = join of disks like `512 GB SSD` (size rounded, type as reported, joined with ` + `); model = `<manufacturer> <model>` (no duplicate manufacturer word); serial = the case's serial.
Tests in `tests/test_form_fill.py`: build small docx fixtures in the test with the same table shapes (Mylo shape and B.tech shape, including an empty cell without runs and a cell with a split run); assert each cell text; assert untouched cells are byte-identical; an arabic engineer name works. Also a test against the real `forms/Mylo.docx` and `forms/B.tech.docx` (they are in the repo): fill with sample hardware and assert the values appear in the right row.

5.2 Service: `FormService.generate` collects hardware from the case's agent report (latest report stored for the case; find it with `grep -n "agent_report" app/services/handovers.py | head`). No report yet: the form still generates (cells empty) and the response header `X-Form-Hardware: missing` lets the UI show the chip `No device report`.

5.3 Print. A browser cannot print a Word file, so the server makes a PDF and the browser prints it:
- Check LibreOffice: `which soffice libreoffice`; it works in the owner's test environment (verified: converting `forms/Mylo.docx` to PDF renders the Arabic text correctly). Add `app/services/pdf_render.py` with `docx_to_pdf(docx_bytes) -> bytes | None`: writes to a temp dir, runs `soffice --headless --convert-to pdf --outdir <tmp> <file>` with `subprocess.run(..., timeout=60)` (list arguments, no shell), returns bytes, or `None` when `soffice` is missing or fails (log one line, never raise). Use a private `-env:UserInstallation=file://<tmp>/profile` argument so parallel runs do not clash.
- Endpoint: `GET /api/handovers/{id}/form?format=pdf` returns `application/pdf` with `Content-Disposition: inline`. `format=docx` (default) keeps the download. If PDF is requested but conversion is unavailable: 503 with `PDF printing is not available on this server`.
- UI: **Print form** fetches `format=pdf`, puts the blob in a hidden `iframe` (object URL; CSP: check `frame-src`/`object-src` in `app/middleware` or the CSP config and allow `blob:` ONLY for this if needed) and calls `iframe.contentWindow.print()`. If the PDF request fails with 503, fall back to downloading the docx and show one line `Printing is not available. File downloaded`. Add a small secondary link **Download Word** next to Print.
- Deployment: look in `deploy/` for the Dockerfile that builds the portal image (`grep -rn "FROM " deploy | head`). Add `libreoffice-writer-nogui` (or `libreoffice-writer`) and fonts (`fonts-noto-core`, `fonts-noto-ui-core`, `fonts-dejavu-core`, `fonts-kacst` or Noto Naskh Arabic: `fonts-noto-naskh`... pick the package names that exist in the base image's apt) to the image, with `--no-install-recommends`. Document it in `docs/` deployment guide and add a line in `tests/test_deployment_guide_config.py` only if that test enforces the guide.
- `tools/check_pdf_render.py`: converts `forms/Mylo.docx` and `forms/B.tech.docx`, prints `OK <pages> page(s)` using the PDF header (count `/Type /Page`), exits non-zero on failure.
Tests: `docx_to_pdf` with a fake runner (monkeypatch `subprocess.run`) for success, timeout and missing binary; endpoint tests for pdf, docx and 503; a real conversion test that is skipped when `soffice` is missing (`shutil.which`). Playwright: clicking Print calls the pdf URL (assert the request) and does not trigger a download event.
Live: run the real conversion for both templates here; save PDF pages as PNG with `pdftoppm -r 60` and inspect (or ask the owner to inspect `docs/review/v2/form-*.png`) that Processor, RAM, Hard Disk, Model, Serial and the engineer name are in the right cells.
Close the part.

---

## PART 6 Cancel, delete, and never lock a device
Owner: a handover was started, then a fault was found and the device must go to maintenance; the system says "an open case exists" and the engineer cannot cancel or delete it. A loop.

Facts: the unique index `uq_handovers_active_device_serial` (migration `0003_independent_operations.py`) allows ONE active case per serial across both kinds, so an open handover blocks a maintenance case (and the reverse). `HandoverService.cancel` exists (`app/services/handovers.py`) and `POST /api/handovers/{id}/cancel` exists, but no screen uses them.

6.1 Per-kind uniqueness: migration `0015_active_per_kind.py`: drop `uq_handovers_active_device_serial` and create it again on `(kind, lower(device_serial))` with the same active condition (`status NOT IN ('completed','closed_with_gaps','cancelled')`). Look at the old definition at lines 75-95 of `0003_*` and copy the column expression exactly (it may already use `lower`). Keep `uq_handovers_active_maintenance_serial`. Test upgrade, downgrade, upgrade on a throw-away database. Tests: an open handover and an open maintenance case for the same serial can both exist; two open handovers for one serial still conflict; two open maintenance cases conflict.
6.2 Maintenance add with an open handover: `POST /api/maintenance/cases` succeeds and the response contains `open_handover: {id}` when one exists. The Devices screen shows under the new row the line `Open handover` with the button **Cancel handover** (calls the cancel endpoint). A handover start for a device with an active maintenance case shows the chip `In maintenance` in the drawer; Start still works.
6.3 Cancel in the UI: the case header gets a menu **More** with:
- **Save and exit**: goes back to the dashboard; the case stays open; toast `Saved`.
- **Cancel case**: confirmation dialog (buttons **Cancel case** and **Keep**; optional short reason field), then calls `/cancel` and returns to the list. One plain line in the dialog: `Snipe-IT is not changed`. The cancelled case disappears from lists and tiles.
- **Delete case**: confirmation dialog (buttons **Delete** and **Keep**); allowed only when the case is not Complete. It permanently removes the case, its parts and its events from the portal database (new `DELETE /api/handovers/{id}`, service method `delete`, one transaction, writes one application log line with the serial and actor, never touches Snipe-IT, returns 409 `Complete cases cannot be deleted` for completed ones).
- **Reopen**: shown on cancelled cases (existing endpoint).
The dashboard rows and the list rows get a small `...` menu with **Cancel case** and **Delete case**. The maintenance case page gets the same menu (Cancel and Delete for cases that are not returned), using the same endpoints (they work on both kinds).
Tests: cancel from the page frees the serial and a new handover can start; delete removes the rows (and the events), refuses a Complete case; Snipe-IT client is never called (fake client assert); Playwright: the owner's story (start handover, then add the same serial to maintenance, then cancel the handover from the Devices screen, no error).
Live proof: with the dev Snipe-IT, `TEST-SN-0003` with an open handover; add maintenance for it (works); status in Snipe-IT becomes Maintenance; cancel the handover; the maintenance case remains.
Close the part.

---

## PART 7 Devices page with a vertical history
Owner: a page for devices where the whole history of one device can be read vertically: handovers, entering maintenance, sending to maintenance, returning.

7.1 Data (service `app/services/device_history.py`, repository query in `app/repositories/`): for a serial (normalized, case-insensitive) collect ALL cases of both kinds (including cancelled) with their events, and for maintenance cases the dates from `MaintenanceInfo` (received, sent, returned, vendor, reason, days). Build a single list of timeline entries sorted by time DESCENDING (newest first), each: `{time, kind: "handover"|"maintenance", title, detail, actor, case_id, case_url}`. Entry titles (short): `Handover started (Lab + user)`, `Checked out to <name>`, `Checked in from <name>`, `Form printed`, `Signed scan attached`, `Handover complete`, `Ready lab`, `Handover cancelled`, `Received for maintenance (<reason>)`, `Status set to Maintenance`, `Checked in from <user>` (maintenance take back), `Sent to <vendor>`, `Returned from <vendor> (<n> days)`, `Status set to Ready to deploy`, `Case cancelled`. Map the existing event types (look at the sentence builder behind `/handovers/{id}/history`, `app/routers/pages.py` around line 757 and `templates/case_history.html`) instead of inventing a second one; reuse its sentences where they exist.
Endpoints: `GET /api/devices?q=<text>&company=<name>` (devices known to the portal: distinct serials with model, company, last state, open case info; search by serial, tag, model) and `GET /api/devices/{serial}/history`.
7.2 Pages: `/devices` and `/devices/{serial}`. Add **Devices** to the left rail and bottom bar as a THIRD group item below Maintenance (label `Devices`, own icon). Keep Sync route as is.
- `/devices`: search box (serial, tag, model), company filter, a table: serial (mono), model, company chip, current place (`Ready lab`, `With <user>`, `At vendor <name>`, `With IT`), last activity time, row click opens the device.
- `/devices/{serial}`: header with serial, model, company chip, live Snipe-IT status and holder (reuse the device-lookup service; if Snipe-IT is down show `Snipe-IT unavailable` and continue). Buttons: **New handover**, **Add to maintenance** (prefilled serial). Below it the VERTICAL timeline: a thin vertical line with a dot per entry, the time on one side, title and detail on the other, colour by kind (handover = mint, maintenance = amber; a text label always carries the meaning), the case link on each entry. Group by month with a sticky month label. Empty device: `No history`.
- Link from everywhere a serial is shown (dashboard rows, lists, case headers) to `/devices/{serial}`.
Rules: short labels; both themes; no horizontal scroll at 390 and 1440 px; strict CSP; script `static/js/devices.js`.
7.3 Tests: history for a device with two handovers and one maintenance (sorted newest first, correct titles, vendor and days); search; unknown serial returns an empty list not a 500; Playwright: open the page from the nav, search, open a device, see the vertical timeline with entries of both kinds, follow a case link.
7.4 Live proof: run the TEST scenarios from PART 2-6 for `TEST-SN-0002`, then open its history through the API and assert the expected entries exist in order.
Close the part.

---

## PART 8 User not yet in Snipe-IT: code, username, daily check, auto-link
Owner: when the user does not appear yet, the engineer enters the employee code and the username; the system checks every day until the user appears, then links the device to him automatically. The signed scan is uploaded to the device either way.

8.1 Migration `0016_pending_user.py`: add to `handovers` nullable `recipient_employee_code` (60), `recipient_username` (120), `pending_checked_at` (datetime), `pending_found_at` (datetime). Test up, down, up on a throw-away database.
8.2 Server:
- `POST /api/handovers/{id}/recipient` with `{"mode": "pending_user", "employee_code": "...", "username": "...", "name": "..."}`: at least one of code and username required, trimmed, max 60 and 120; sets mode `pending_user`; records RECIPIENT_CHECK `not_done` with reason `User not in Snipe-IT yet`; tries one lookup immediately.
- Service `app/services/pending_users.py`: `check_pending_users(session, client)` for every open case in mode `pending_user`: look up by `username` first (`find_user`), then by employee code (`search_users`; verify with the live probe that Snipe-IT finds users by employee number; if it does not, STOP and tell the owner). Update `pending_checked_at`. Exactly one user found: link him (set mode `snipeit`, store the recipient fields and company, RECIPIENT_CHECK passed, run the recipient-items check, auto-pass when empty), event `pending_user_found`. If the user's company differs from the device's: link anyway with the warning (warning never blocks). Do the automatic check-out ONLY when the device status is Ready to deploy, the device is not held by someone else and there is no company warning; otherwise leave the check-out to the engineer and show the chip `Check out manually`. More than one match: event `pending_ambiguous`, do nothing.
- Background loop in the app lifespan (`asyncio` task, no new dependency): every `PENDING_USER_CHECK_HOURS` (config, default 24; `PENDING_USER_CHECK_ENABLED` default true); catches every exception and logs one line; stops cleanly on shutdown.
- `POST /api/handovers/{id}/pending-user/check` (one case) and `POST /api/handovers/pending-user/check-all`.
8.3 UI: the Waiting-user card shows employee code, username, `Last checked <time>`, **Check now**, **Change**. The Recipient form for type User not ready has two fields (Employee code, Username) and an optional Name. The dashboard rows show the chip `Waiting user`; the dashboard top bar gets a small button **Check waiting users** (calls check-all, then refreshes).
8.4 Read the user from the device (optional field): in the agent script and report add `logged_on_user` (string, max 200; `(Get-CimInstance Win32_ComputerSystem).UserName`, fallback the most recently used non-special profile folder name). Find them with `grep -rn "Get-CimInstance" app templates static | head`. The server keeps it optional so old scripts still work. The Recipient/Waiting card shows `On device: <value>` and a button **Use** that fills the Username (strip `DOMAIN\` or `AzureAD\`). The portal never links by itself from this value. Unit-test the strip function (`CORP\ali.hassan`, `AzureAD\Ali Hassan`, `ali.hassan`).
Tests: found by username; found by employee code; company difference links with the warning and skips auto checkout; not found only updates the time; two matches do nothing; the loop function survives an exception (fake client).
Live proof `tools/v2_probe_pending_user.py` (TEST data): case for `TEST-SN-0002` in `pending_user` with username `test.newuser1`, code `EMP-TEST-1`: check, still waiting; create that user in Snipe-IT through the API (company B.tech, `employee_num` `EMP-TEST-1`); check: linked (Snipe-IT user id matches), device checked out when eligible; repeat with a Mylo user: linked with warning, not checked out; search by code only works; clean up users and cases.
Close the part.

---

## PART 9 Final verification
9.1 Full `pytest -q` once (with a timeout), `ruff check .`, `tests/test_architecture_rules.py`, `tests/test_graph_consistency.py`, `npm run build:css` (no diff afterwards).
9.2 Live scenarios in `tools/v2_verify_all.py` (extend, do not rewrite): types (Lab only to Ready; Lab + user to Complete; User not ready to Not complete then linked); device holder and Check in; Check out always, same user, replace holder; form with hardware (PDF produced and the docx cells contain the values); cancel and delete; maintenance with an open handover; device history order; pending user. Save to `docs/v2-verification.md` under "Polish" with the commit id and short excerpts (no secrets).
9.3 Playwright journey through everything and a crawl of every nav link (all 200, none shows `{"detail":"Not Found"}`, no silent buttons). Screenshots to `docs/review/v2/`: dashboard (3 tiles), case page for each type, device page timeline, forms rendered to PNG.
9.4 `docs/OPEN_QUESTIONS.md`: Nexta template missing; the Mylo form header shows a B.tech logo and the company text `بي تك للتمويل` (owner to confirm); PDF printing needs LibreOffice in the deployment image; the delete rule (Complete cases cannot be deleted).
9.5 Commit, push `feature/v2-polish` (normal push). Do NOT merge. Final message to the owner: commit id, scenarios passed, screenshot folder, and the owner actions still open.
