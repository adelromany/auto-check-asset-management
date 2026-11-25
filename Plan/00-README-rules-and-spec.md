# V2 build: Handover + Maintenance with real Snipe-IT integration (READ THIS FIRST, EVERY NEW CHAT)

You are a coding model with a SMALL context (about 100k tokens per request, 31k output). The work is split into small phase files `01` to `08`. You do ONE phase at a time, in order. This file holds the rules and the owner's spec. Keep it short in your head: re-read only the "Spec" and the phase file you are on.

## A. How to work (obey always)
1. **Branch:** `git fetch origin && git checkout -b feature/v2-handover-maintenance origin/fix/ui-recovery` (tip `265b26c`). If the branch exists, `git checkout` it. Never commit to `main`. Never force-push. Never commit `.env`, tokens, `data/*.db`.
2. **Memory file:** keep `HANDOFF-V2.md` in the repo root. After EVERY step append one line: `STEP x.y DONE <what> <test result>`. It is your memory between chats. Read it first in every new chat.
3. **Never read big files whole.** Use `grep -n "word" file`, then `sed -n 'A,Bp' file` (max 60 lines). Never open `package-lock.json`, `node_modules`, `__pycache__`, generated HTML/PNG, `docs/principles/visual/*`, or `reference-demo.html` as a whole.
4. **One step = one small edit + one targeted test.** Run only the tests named in the step. Run the full suite only at the end of a phase: `pytest -q -p no:cacheprovider --deselect tests/test_clipboard_playwright.py` (known environment errors in browser tests: report them, do not hide them).
5. **Context guard.** After about 25 tool calls, or after any very long tool output, or when you notice yourself repeating: STOP. Update `HANDOFF-V2.md`, commit what is green, then tell the owner exactly: "Context is getting full. Please open a NEW chat and paste the START MESSAGE from 00-README." Do not continue in a crowded context.
6. **Two failures rule.** If the same command fails twice with the same error: stop, write the exact error in `HANDOFF-V2.md`, ask the owner. No guessing, no loops.
7. **Commits:** small, one per green step: `feat(handover): ...`, `test: ...`. End every commit message with the two attribution lines the harness gives you, if any.
8. **Tests are part of the work.** Every new rule gets a test. You MAY change existing tests only when the owner's new spec (section B) changes that behavior; say which tests you changed and why in `HANDOFF-V2.md`. Never delete a test to make it pass.
9. **Layering (do not break):** routers -> services -> repositories/clients -> db/external. `app/domain/` is pure (no I/O). `tests/test_architecture_rules.py` must stay green.
10. **Security stays:** CSRF on writes, strict CSP (no inline scripts/styles), `textContent` not `innerHTML` with data, SSO roles unchanged, no secrets in logs. No new runtime dependency without asking the owner (use `zipfile`, `re`, `xml` from the standard library).
11. **UI text rule (owner demand):** only short labels and verbs ("Check device", "Print form", "Send batch"). No explanatory sentences, no marketing words, no "AI-sounding" text. Errors: one plain line saying what to do.
12. **Integration is the top priority.** A feature that talks to Snipe-IT is not done until it passed against a REAL Snipe-IT (the dev stack in `deploy/snipeit-dev`) and the result is written in `docs/snipeit-integration-report.md`. A fake client alone is NOT proof.

## B. Spec (the owner's decisions; the source of truth)
The app has two separate sections. They share only login and the Snipe-IT client. No shared numbers, dashboards or statistics.

### B1. Handover (create a Handover case)
A case follows these parts. Each part is independent and recorded. Result of the case: **Complete** (all parts passed) or **Not complete yet** (something missing). Not-complete cases can be continued later.
1. **Device status (Snipe-IT):** read the device by serial; show its status label and **company**; let the engineer change the status. Passed when the status is "Ready to deploy".
2. **Hardware + software check by the command** (existing agent flow, short code + one-line command, unchanged).
3. **Engineer** = the signed-in SSO user. Automatic, shown as a fact.
4. **Handover form** by device company: a Word template per company (`forms/B.tech.docx`, `forms/Mylo.docx`; Nexta later). Only the engineer name is filled (placeholder `{{ENGINEER}}`). Everything else stays empty.
5. **Recipient:** choose a Snipe-IT user, OR "None for now", OR "Not in Snipe-IT yet" (free name + email). The recipient's company must equal the device's company (block when both known and different).
6. **Recipient's current items in Snipe-IT:** show them; the engineer can take back (check in) any of them.
7. **Check out** the device to the recipient in Snipe-IT.
8. **Signed paper:** upload the scan; it is attached to the device in Snipe-IT.
- "None for now" makes the case a **Ready lab** (device checked, waiting for a recipient). It can be assigned later.
- Dashboard: Ready labs grouped by owning company, Complete, Not complete yet. Clicking any of the three lists its cases; Not-complete and Ready cases can be continued.

### B2. Maintenance (separate)
1. **Add device:** type the serial; the system pulls model, company, category, status and current user from Snipe-IT. Buttons: **set Snipe-IT status to Maintenance**, **take back from the user** (only if assigned). A **reason** list (many reasons + "Other" which opens a text box) and an optional planned vendor.
2. **Send batch:** select several devices, choose the date and the maintenance company, send.
3. **Receive batch:** select devices, choose the date, receive; their Snipe-IT status becomes **Ready to deploy**.
4. **Dashboard:** devices that need maintenance, and devices in maintenance, each grouped by device model, owning company, and maintenance company; for devices in maintenance also the number of days there.
- States (derived from recorded operations): Needs maintenance, In maintenance, Returned from maintenance.
- There is no stock/warehouse concept. Vendors ("maintenance companies") are a list inside the portal (Snipe-IT has no suppliers here).
- Three owning companies: B.tech, Nexta, Mylo (names come from Snipe-IT companies).

### B3. Domain facts already in the repo (verified, do not re-research)
- `app/clients/snipeit.py` already has: `find_user`, `search_users`, `get_user`, `list_user_assets`, `get_asset_by_serial`, `get_asset`, `checkout_asset_to_user`, `checkin_asset`, `upload_asset_file`, `list_asset_files`, `whoami`, `list_status_labels`, `update_asset_status`. DTOs `SnipeItAsset`/`SnipeItUser` have NO company yet.
- Operations framework: `app/domain/catalog.py` (operation keys and per-kind lists), `app/domain/stages.py`, `app/domain/handover_rules.py` (`derive_status`), `app/domain/maintenance_rules.py`, services in `app/services/`, API in `app/routers/handovers.py`, pages in `app/routers/pages.py`, templates in `templates/`, JS in `static/js/`, migrations in `alembic/versions/` (latest `0006_maintenance_priority.py`).
- Config for maintenance status names exists as `SNIPEIT_STATUS_NEEDS_MAINTENANCE/IN_MAINTENANCE/RETURNED` (empty by default). V2 replaces them with two names (phase 06).
- Visual reference: `docs/ui/reference-demo.html` (copy of the approved demo; ONLY read one function at a time with `grep -n "function devPanel" -A 40`).

## C. Phases
| File | Phase |
|---|---|
| 01 | Snipe-IT integration: live dev instance, seed data, client extension, probe report (GATE) |
| 02 | Handover: operation catalog, migration, create case, device status |
| 03 | Handover: recipient, company rule, recipient items |
| 04 | Handover: form by company, signed paper, outcome (Complete / Not complete / Ready) |
| 05 | Handover UI: workspace and dashboard |
| 06 | Maintenance backend: add device, reasons, batches, dashboard data |
| 07 | Maintenance UI |
| 08 | Final live verification and docs |

Do not start phase N+1 until phase N is green and written in `HANDOFF-V2.md`. Phase 01 is a GATE: if any Snipe-IT call fails there, stop and tell the owner.

## D. START MESSAGE (the owner pastes this in a NEW chat when the context is full)
```
Continue the V2 build. Files 00 to 08 (00-README-rules-and-spec.md and the phase files) are in the repo folder docs/v2/.
1. Read ONLY 00-README-rules-and-spec.md sections A and B, then HANDOFF-V2.md.
2. Run: git branch --show-current ; git status --short ; git log --oneline -5
3. Open ONLY the phase file named in the last line of HANDOFF-V2.md and continue from the first step not marked DONE.
4. Follow the rules in section A (small reads, small tests, update HANDOFF-V2.md after every step, ask me for a new chat when the context is getting full).
```
