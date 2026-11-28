# 15: Addendum to file 14 (form fields, buttons that must disappear, device history design)

Use together with `14-polish-from-92f0679.md`. Same rules as its PART 0 (one model at a time, lock line, small steps, two-failure rule, context guard, live proof, timeouts). Put this file in `docs/v2/`.

How to apply:
- If PART 5 of file 14 is NOT done yet: read section A here BEFORE doing PART 5 and follow A where it differs.
- If PART 7 is NOT done yet: build it from section C here instead of the PART 7 timeline design (keep PART 7's routes, search and data endpoints).
- If those parts are already done: do A and C as follow-up fixes.
- Section B is new and applies to the whole UI. Do it as its own part after PART 6 (or after PART 7 if those are already done), then run the final verification of PART 9 including these items.

Track in `HANDOFF-V2.md` as `ADDENDUM A`, `ADDENDUM B`, `ADDENDUM C`.

---

## A. Form: also fill device type (Model) and Serial; company name check

Verified facts about the templates in `forms/`:
- `Mylo.docx`: first table has rows `Model | (empty cell)` and `Serial | (empty cell)`. Handled by PART 5 as two-cell rows.
- `B.tech.docx`: NO table for these. There is ONE paragraph with the text `SN :                            Model : ` (the label `SN :` and the label `Model :` in the same paragraph, spaces between them, runs may be split). The serial goes right after `SN :` and the model right after `Model :`, in the same paragraph.

A1. Extend `fill_form(docx_bytes, *, engineer, hardware)` in `app/domain/form_fill.py` with the inline-label rule:
- Find a paragraph whose joined text contains `SN` followed by optional spaces and `:` and also `Model` followed by `:` (case-insensitive). In that paragraph rebuild the visible text as `SN : <serial>      Model : <model>` (keep the original label spellings; keep 6 spaces between the two groups). Put the whole new text in the FIRST `<w:t>` of the paragraph (with `xml:space="preserve"`) and empty the other `<w:t>`, exactly like the split-run logic for the placeholder. Keep every run property.
- A paragraph that has only one of the two labels (for example `Serial : ...` alone): fill only that label.
- Missing value: leave the original text of that part untouched (do not write empty text over the labels).
- If a template has BOTH a two-cell `Model`/`Serial` table row and the inline paragraph, fill both.
A2. Values: `model` = `<manufacturer> <model>` from the agent report (no duplicated manufacturer word), falling back to Snipe-IT's `device_model` stored on the case when there is no report; `serial` = the case serial (the Snipe-IT serial). The report is NOT required for these two.
A3. Tests in `tests/test_form_fill.py`: a fixture with the B.tech paragraph shape (labels split over 3 runs, many spaces) gives `SN : TEST-SN-0001      Model : Dell Latitude 5440`; a fixture with only a table (Mylo shape); both together; a missing model keeps the label; the real `forms/B.tech.docx` and `forms/Mylo.docx` contain the serial and model after filling (assert by reading `word/document.xml` text). Re-run the PDF conversion of both filled files and inspect the PNG pages (or ask the owner to look at `docs/review/v2/form-*.png`).
A4. Company name: CONFIRMED CORRECT by the owner. The Mylo template's logo and company text are right as they are. Do NOT change, flag or ask about them. Remove any note about it from `docs/OPEN_QUESTIONS.md` and ignore the Mylo name item in file 14 (PART 9.4). The code writes no company name; no `{{COMPANY}}` placeholder is needed.

---

## B. Buttons that stay after they are used (UI rule, applies everywhere)

Problem: after clicking a one-way action button (for example **Set Maintenance**, which changes the status in Snipe-IT) the button stays on the screen, which looks wrong.

Rule: an action button is shown ONLY while its action is still applicable, and the decision comes from the SERVER state in the last response, never from a local flag.
- When the action has finished successfully, the button is REPLACED by a small done chip (green check + short label, for example `✓ Maintenance` or `✓ Checked in`), not just disabled.
- When the action is not applicable (for example **Check in** when the device is not assigned), the button is not rendered at all.
- When the action failed: the button stays, with the one-line error under it and **Retry** only if the action can be repeated.
- While running: the button shows a small spinner and is disabled.
- Exception, decided by the owner: **Check out** (handover) stays clickable when a recipient exists (PART 4 of file 14); the owner wants to repeat it.

B1. Inventory first (read only): `grep -n "Set Maintenance\|Check in\|Remove from user\|Apply\|Retry\|Send batch\|Receive batch\|Cancel handover" templates static/js | cut -c1-130`. Write the list of buttons and the condition that makes each applicable in `HANDOFF-V2.md`, for example:
- Maintenance row **Set Maintenance**: applicable while the device status in Snipe-IT is not the Maintenance label (`SNIPEIT_STATUS` part not passed or the stored `snipeit_status_name` differs).
- Maintenance row **Check in** (remove from user): applicable while the device is assigned (holder stored on the case).
- Handover **Check in** (holder) and **Check in** (other devices): applicable while there is a holder or unchecked items.
- **Apply** (status select): applicable when the selected label differs from the current status; otherwise disabled with no extra text.
- **Retry** buttons: only when that part is failed.
B2. Implement one small shared helper in `static/js/shell.js` (or the existing helper file): `portal.actionSlot(host, {applicable, done, doneLabel, label, onClick})` that renders the button, the done chip, or nothing, and use it for every button in the inventory. No per-page copies of this logic.
B3. Server support: maintenance case rows and the handover case DTO must carry the facts the UI needs (`snipeit_status_name`, `device_holder_name`, per-part states) so the UI can decide after every response. After each action the page re-renders the row or panel from the response (no full reload).
B4. Tests: Playwright for each button in the inventory: click, wait, assert the button is gone and the done chip is present; a failing action (fake client error) keeps the button and shows the line; reloading the page keeps the same display (state comes from the server). Unit test for the helper logic if the repo has JS tests; otherwise cover it through Playwright.
B5. Live proof with the dev Snipe-IT: add `TEST-SN-0004` to maintenance, click Set Maintenance: the chip `✓ Maintenance` shows and the button is gone; Snipe-IT status read back is Maintenance; reload keeps it.

---

## C. Device history: useful and organized, like the owner's sample (NOT every small event)

The owner's sample (a maintenance history page): a date as a heading, then one rounded card per milestone. Inside the card a light-grey panel: on the left a small kind tag (`Mac Maintenance`) and a bold headline (`Dispatched to Vendor · WI-FI`, `Returned from Maintenance · screen Defected`); on the right small fact boxes, each with a tiny uppercase label over a bold value (`STATUS` with a coloured chip `In Maintenance` or `Maintenance Completed`, `VENDOR FixTech`, `COMPANY Mylo`). Clean, scannable, few items.

Replace the "every event" timeline of PART 7.1 and 7.2 with MILESTONE cards. Do not list prints, uploads, status changes, searches, retries or check-ins; those stay in each case's own History page (existing).

C1. Milestones (service `app/services/device_history.py`; one pure function builds cards from already-loaded cases; no per-event queries):
- Handover that is Complete: one card dated at completion. Tag `Handover`. Headline `Handed over to <recipient name>`. Facts: `STATUS` = `Complete`, `USER` = recipient, `COMPANY` = recipient company (with `!` chip if it differs from the device), `ENGINEER` = engineer name.
- Handover that is a Ready lab: tag `Handover`, headline `Prepared as Ready lab`, facts `STATUS Ready lab`, `ENGINEER`.
- Handover still open: ONE card dated at creation, headline `Handover in progress`, facts `STATUS Not complete`, `USER` (or `Waiting for user`), `MISSING` = the first three missing parts; the card links to the case.
- Handover cancelled or deleted: NOT shown.
- Maintenance: one card per milestone that happened, each dated at its own date: `Received for maintenance · <reason>` (facts `STATUS With IT`, `COMPANY`, `FROM` = the user it was taken back from when known), `Dispatched to <vendor> · <reason>` (facts `STATUS In maintenance`, `VENDOR`, `COMPANY`, `DAYS` so far or at dispatch), `Returned from <vendor> · <reason>` (facts `STATUS Maintenance completed`, `VENDOR`, `COMPANY`, `DAYS` total in maintenance). Tag `Maintenance`. A cancelled maintenance case is not shown.
- Sort newest first; group by date (heading `dd/mm/yyyy` in the app's date format); the same day keeps newest first.
- Each card links to its case (`case_url`).
Output per card: `{date, tag, headline, facts: [{label, value, kind}], case_url}` where `kind` is `chip-ok`, `chip-warn`, `chip-info` or `plain` (the UI maps it to token colours; text always carries the meaning).

C2. Summary strip at the top of `/devices/{serial}` (live and short, four boxes): `NOW` (Ready lab / With <user> / At vendor <name> / With IT, from the portal's latest case plus the live Snipe-IT holder), `HANDOVERS` (count of complete), `MAINTENANCE` (count of maintenance cases and total days), `LAST ACTIVITY` (date). If Snipe-IT is unreachable the `NOW` box falls back to the portal's data with the chip `Snipe-IT unavailable`.

C3. UI (`templates/device_detail.html`, `static/js/devices.js`, classes in `styles/app.css`, tokens only):
- Cards copy the sample's structure: outer card with the date as a heading above it; inner light panel (`surface-2` token); left = kind tag chip + bold headline; right = fact boxes in a wrapping grid (each box: tiny muted uppercase label, bold value, soft border). Handover cards use the mint accent on the tag, maintenance cards the amber accent; the tag text always says which.
- A thin vertical rail on the left connecting the date headings (keeps the "vertical history" the owner asked for), dots at each date.
- On phones the fact boxes drop under the headline.
- Empty: `No history`. No long sentences. Both themes. No horizontal scroll at 390 and 1440 px.
C4. `/devices` list stays as in file 14 (search, company filter, table with current place and last activity).
C5. Tests: unit tests for the pure card builder (a device with: one complete handover, one open handover, two maintenance cases, one cancelled case: exactly the expected cards, in order, with the expected facts; none for cancelled; `DAYS` correct); API test for `/api/devices/{serial}/history` shape; Playwright: open a device, assert date headings and cards, no card for a print or upload action, follow a card link; screenshot `docs/review/v2/device-history-light.png` and `-dark.png` (desktop and 390 px).
C6. Live proof: run the TEST flows for `TEST-SN-0002` (a complete handover, then a maintenance case sent and returned) and assert the history API returns exactly: Returned card, Dispatched card, Received card, Handover card, in that order, with vendor and company facts.

---

## D. Closing
Update `docs/v2-verification.md` with the three addenda results, run the full suite once, `ruff check .`, `HANDOFF-V2.md` `ADDENDUM A/B/C DONE <commit id>`, lock `IDLE`, commit and push `feature/v2-polish`. Final message to the owner: commit id, what changed, screenshot paths, open owner actions (Mylo logo and legal name inside the template; Nexta template).
