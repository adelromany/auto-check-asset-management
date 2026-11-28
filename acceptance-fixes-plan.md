# Acceptance fixes plan — round 3 (2026-11-28)

Project: FastAPI + Jinja + vanilla JS handover portal. Respect `docs/principles/*` (tests first, domain rules pure, UI tokens in `static/css/app.css`). Every fix ships with a test. Do not touch `data/*.db`, `.env`, `.venv`.

## 1 + 3. Lab-only case stays "Not complete" / Device status never passes if unchanged (same root cause)

**Cause:** `static/js/handover-case.js` → `renderStatusAction()` makes the Apply button applicable only when `selectedName !== detail.snipeit_status_name`. When the device is already "Ready to deploy", nothing can be pressed, so `Operation.DEVICE_STATUS` stays `pending`. `case_outcome()` (`app/domain/handover_rules.py`) needs DEVICE_STATUS + AGENT_REPORT + SOFTWARE_CHECK all `PASSED` for a Lab-only case, so the case never reaches `READY` and the list shows it under Not complete.

**Fix:**
- Backend (`app/services/snipeit_ops.py::set_device_status`): already supports `status_label_id=None` (verify-only). Also call that verify path automatically whenever the live device is read (`device_live` / `refresh`) and the current Snipe-IT status equals `SNIPEIT_STATUS_READY`, then pass DEVICE_STATUS if it isn't passed yet. Do this at case creation too (`create()`): the device facts are already loaded there.
- Frontend: when the selected status equals the current one, show a **"Confirm status"** button (POST `/device-status` with `status_label_id: null`) instead of a disabled Apply.
- After any operation, `recompute_status` must leave a Lab-only case with the 3 required parts passed at `READY` even when the non-required parts are still pending. Add a regression test: create Lab-only case on a device already "Ready to deploy" → agent report + software check pass → status `ready`, appears under `outcome=ready` in `/handovers`.
- Check that nothing else blocks it: walk the full Lab-only flow in a test with the Snipe-IT fake (`tests/fakes/snipeit_fake.py`) and assert the list filter result.

## 2. Print button downloads the Word file instead of printing

**Cause:** not the printer. `/api/handovers/{id}/form?format=pdf` calls `app/services/pdf_render.py::docx_to_pdf`, which uses `shutil.which("soffice")`. LibreOffice isn't on PATH on the Windows server → returns None → 503 → JS falls back to `downloadWord()` with "Printing is not available. File downloaded".

**Fix:**
- `pdf_render.py`: find the executable from config `SOFFICE_PATH` (new, optional, add to `config.py` + `.env.example`), then PATH, then the standard Windows paths `C:\Program Files\LibreOffice\program\soffice.exe` and `C:\Program Files (x86)\...`.
- Optional second converter on Windows: Microsoft Word via COM (`pywin32` / `docx2pdf`), used only if LibreOffice isn't found and the import works. Guard it so tests/Linux don't break.
- `scripts/setup.ps1`: detect LibreOffice and print a clear message if it's missing (do not install anything automatically).
- `GET /api/health` (or the existing health route): report `pdf_print: available|unavailable` so it can be checked in one glance.
- JS message when 503: "PDF printing needs LibreOffice on the server — Word file downloaded instead." Keep the fallback.
- Docs: add a short section in `docs/deployment/INSTALL-WINDOWS.md`.

## 4. Recipient: search by employee code + use the device's current user

Today: free-text search goes to Snipe-IT `/api/v1/users?search=`; the candidate cards show name/email only.

**Fix:**
- `SnipeItClient`: add `find_user_by_employee_num(code)` (use `/api/v1/users?employee_num=<code>`; if the API ignores the filter, search then filter exact `employee_num` client-side). Return `employee_num` in `RecipientCandidate` (DTO) and show it on each card.
- `search_recipients`: if the query looks like an employee code (digits or the company's code pattern, keep it simple: `^[A-Za-z]{0,4}\d{2,}$`) try the exact employee_num match first and put it on top; otherwise keep the current search.
- Recipient panel UI: placeholder "Name, username or employee code". Add two quick-fill buttons above the search:
  - **"Current Snipe-IT holder"** — uses `handover.device_holder_name/id` (already stored) → loads that user as a candidate.
  - **"User signed in on device"** — uses `logged_on_user` from the latest agent report (already in the detail DTO; same logic as the existing `[data-use-logged-user]` in the pending-user panel) → runs the search with the SAM name.
  Hide each button when its source is empty.
- Pending-user panel already has Employee code + Username: make "Check now" also try the employee code against Snipe-IT.
- Tests for the client method, the service ordering, and the DTO field.

## 5. Engineer is not asked on case creation

Engineer already comes from SSO session or the DEV user (`app/routers/handovers.py` uses `_actor(user)`). Remove the read-only "Engineer" field from the New handover modal in `static/js/shell.js` (~line 494). Keep showing the engineer on the case page. Update any test that expects that field.

## 6. Devices page UI redesign

Files: `templates/devices.html`, `templates/device_detail.html`, `static/js/devices.js`, `static/css/app.css`, `app/routers/devices.py` / `app/services/device_history.py` if more data is needed.

Target (follow `docs/ui/DESIGN.md` + `docs/principles/07-ui-ux-principles.md`, existing tokens, light/dark, mobile):
- **List page:** page header with total count; a toolbar with search (serial/tag/model), company select (built from data, not free text), "current place" filter chips (In lab / With user / In maintenance / Unknown), debounce on input. Table → row with mono serial + asset tag, model, company badge, place as a coloured status badge, holder name, last activity as relative time ("3 days ago", exact date on hover). Sortable by last activity. Loading skeleton rows, proper empty state with a hint, error state. On mobile, rows become cards.
- **Detail page:** header with serial, model, company, live Snipe-IT status + holder (with "Snipe-IT unavailable" state); summary tiles (Now, Handovers, Maintenance count/days, Last activity); actions "New handover" / "New maintenance" prefilled with the serial; history timeline grouped by date with the existing milestone cards, cleaned up spacing.
- Take before/after screenshots with the existing e2e capture (`tests/e2e/test_capture_screens.py`) if it runs; otherwise describe the changes.

## Verification
- `pytest -q` green (full suite, not just new tests). `ruff check .` clean.
- Update `HANDOFF-V2.md` with a short "Round 3 fixes" section: what changed, files, how to test each of the 6 points by hand.
