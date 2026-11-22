# Task: Repair the broken UI on `docs/ui-sync`, then rebuild it as four real screens (Dashboard, Handovers, Maintenance, Sync)

Repo `auto-check-asset-management`. Start from the tip of `origin/docs/ui-sync` (9a49d6c). Work on a new branch `fix/ui-recovery`. Never commit to `main`, no force-push. The 12 principle files in `docs/principles/` still apply (security is a red line). Keep the domain, services, repositories, migrations and the existing tests. The templates and the JS of the UI are replaceable.

## 0. Why this task exists (verified by running the branch, not guessed)
The previous UI work looks finished but is not usable. The owner's words: "every feature is cosmetic, any click shows `{"detail":"Not Found"}`, and the screens are mixed up." I ran the branch (uvicorn, a seeded handover case and a seeded maintenance case, Playwright). Findings:

| # | Defect | Evidence |
|---|---|---|
| D1 | A visible link opens a raw JSON error page | Case page link `/api/handovers/{id}/report` returns `404 {"detail":"The agent report is not available for this handover yet."}` and is shown even before any agent report exists. Pages must never link to `/api/...` URLs. |
| D2 | Silent dead buttons | In the case drawer: "Override software check" sends no request and shows nothing; "Push to Snipe-IT" sends no request and shows nothing; the "User signed in" drawer has no action at all. |
| D3 | The shell is not the same on every page | The Dashboard has no left rail and no bottom nav; the other pages do. The rail is icons only (labels appear on hover), so Dashboard and New case look alike. |
| D4 | Two URLs for one screen | `/` and `/dashboard` render the same page; `/handovers` redirects to `/cases`; `/new` is a separate page; Maintenance is only `/cases?kind=maintenance` (a filtered list). |
| D5 | Wrong status | The case card shows the green chip "All operations passed" while it says `0/10 done`. |
| D6 | The logo is cropped | `static/img/b_labs.jpeg` is shown as a small square cropped to a letter. It must be shown whole. |
| D7 | Maintenance is not a feature yet | No vendor board, no "which device is at which vendor and for how many days", no register-maintenance flow of its own; the vendor is a text line "Unassigned". |
| D8 | Raw errors | Any server error on an HTML page is shown as JSON. |
| D9 | The test suite did not catch any of this | Tests only check that pages return 200. Also `tests/test_clipboard_playwright.py::test_insecure_origin...` errors (report it, do not hide it). |

All of D1 to D9 must be closed and proven by the click-through test in Phase 0.

## 1. Rules
1. **Nothing is "done" until the click-through test (Phase 0) is green and you have opened the screenshots yourself.** A feature whose button does nothing is not a feature.
2. Work in the phase order below. Commit after each phase with a clear message. Run the whole test suite after each phase.
3. Every button either (a) performs an action and shows its result (toast, state change), or (b) is disabled with a visible reason ("Run the device check first"). A button that does nothing and says nothing is a defect.
4. HTML pages never contain a link to `/api/...`. Downloads are done by a button that calls the API and opens the result, with a clear message on failure.
5. A browser navigation (header `Accept: text/html`) that ends in an error shows a friendly in-app error page (what happened in one line, a Back button, the request id). API calls (`/api/...`) keep returning JSON. Add one exception handler for this and test it.
6. No new runtime dependencies. No inline scripts or styles (strict CSP stays). Use `textContent`, never `innerHTML` with data. No external requests (self-host fonts).
7. Security unchanged: CSRF on every write, roles from Entra groups, agent surface is code-only. Do not weaken anything for convenience.
8. Do not invent facts. If something needs an owner decision, add it to `docs/OPEN_QUESTIONS.md` and keep going with the most reasonable default.
9. Text is short. Labels one to three words. No paragraphs inside cards. Explanations live behind a `?` tooltip.

## Phase 0. The click-through test (build this FIRST, run it red, then make it green)
Create `tests/e2e/test_clickthrough.py` using the existing Playwright setup. It starts the app on a temp SQLite DB with `SSO_ENABLED=false`, seeds one handover case and one maintenance case (through the API, `TEST-` serials only), and then:
1. **Crawls** every page reachable from the nav and from links on each page (dashboard, handovers, maintenance, sync, one handover case, one maintenance case, history pages). Fails on any `<a href>` that returns 4xx/5xx or a body that is JSON.
2. **Clicks every visible button and link-like control** on each page and in each open drawer (loop over all tiles and rows). For each click it records: network calls, DOM change, URL change, toast. Fails when a click produces none of them (dead button) unless the button is disabled with a visible reason.
3. Fails on any console error, any page error, any 4xx/5xx response whose result is not shown to the user in the UI (a 422 shown as an inline message is fine).
4. Checks that the **same shell** (rail with visible labels on desktop, bottom nav on mobile, top bar) exists on every page, and that exactly one nav item is marked active.
5. Checks `/` is the Dashboard and that each of the four nav items leads to a page with a different `<h1>`.
Commit the test first with its current RED output saved to `docs/ui/baseline-clickthrough.txt` (this documents D1 to D5). It must be green at the end.

## Phase 1. Shell, navigation, logo, error pages (fixes D3 D4 D6 D8)
One base layout `templates/base.html` used by every page. Desktop (1024 px and wider): left rail 220 px wide with icon **and label always visible**; the active item has the mint underscore. Mobile: bottom tab bar with the same four items plus a floating "+" button.

Exactly four destinations:
| Nav | URL | Purpose |
|---|---|---|
| Dashboard | `/` | One view of handovers and maintenance together |
| Handovers | `/handovers` | Monitor and register device handovers |
| Maintenance | `/maintenance` | Register and monitor repairs and the devices at vendors |
| Sync | `/sync` | Check a device without opening the portal on it |

Details:
- Case pages: `/handovers/{id}` and `/maintenance/{id}`; history at `/handovers/{id}/history` and `/maintenance/{id}/history`. Old URLs (`/cases...`, `/new`, `/dashboard`, `/device-check`) answer 308 to the new ones (keep the query string). `/new` goes to `/handovers?new=1`.
- Top bar: only the omnibox (search recipient, serial, asset tag, ticket, vendor; `/` focuses it; results grouped Handovers / Maintenance / Devices) and the user menu with theme toggle. Registration is a **drawer opened by a "New handover" / "New maintenance" button on the relevant screen**, not a page of its own.
- Logo: show `static/img/b_labs.jpeg` whole (no crop), 40 px square, 10 px radius, `object-fit: contain`, placed on a #1A1A1A chip so it blends in light mode; next to it the text "Handover Portal". Never use the old computer icon. Generate favicon PNGs from the JPEG with a committed build script.
- Error page template as in rule 5.

## Phase 2. Visual system (fixes the "not original" complaint, keeps it usable under pressure)
Tokens in `styles/app.css` (CSS variables, light and dark). From the logo: ink `#1A1A1A`, mint `#71E3D9` as the single accent (use a darker mint for text on light, contrast at least 4.5:1), warm off-white `#F6F7F5`. Status colors: amber (needs attention), blue-teal (in progress), green (done), red (failed), grey hatch (not done). One radius scale (8/12/16), spacing 4 px base, two fonts (a mono for serials and numbers, a clean sans), self-hosted.

Signature elements (use all of them, consistently):
1. **Operation strip**: a row of round dots, one per operation, with state icon and hover label. Used on every row and card. It replaces text such as "3 of 10".
2. **Mint underscore** motif: active nav item, active tab, omnibox caret.
3. **Big numbers, small labels** on dashboard tiles, with a short count-up (about 300 ms, off under `prefers-reduced-motion`).
4. **Calm density**: generous whitespace, one focal point per screen, status shown by icon plus word (never color alone).
5. Dark theme is first-class (an engineer may work in a dim room); remember the choice.

Built for a pressured engineer (these are measurable, test them):
- The most common task on each screen takes at most **two clicks** from the screen (register a handover, open a case, mark an operation done, send a device to a vendor, mark it returned).
- Hit targets at least 40 px high. Primary action is always the same position and color.
- Keyboard: `/` search, `n` new (on Handovers and Maintenance), `Esc` closes drawers, `Enter` submits the focused form, arrow keys move between tiles.
- Lists refresh by themselves every 15 seconds with a small "Updated just now" indicator and no layout jump; drawers and forms are never reset by a refresh.
- No modal on top of a modal. Destructive actions (cancel case) ask once, with an Undo toast where possible.
- Filters and sort choices are remembered (localStorage in try/catch) and shown as chips.
- Empty states are one line and one button. Loading states are skeletons, not spinners over blank screens.

## Phase 3. Dashboard (`/`)
Answers "what needs me now?" for both case types. Layout, top to bottom:
1. Row of five tiles: **Handovers open**, **Handovers stalled/with gaps**, **Needs maintenance**, **At vendor**, **Returned this week**. Each tile is a link that opens the right screen already filtered.
2. **Needs attention** list (max 8 rows): type icon, serial, one-line reason (stalled 24 h, failed operation, overdue at vendor, not done), operation strip, age, one button "Open". Sorted by urgency.
3. Two small side-by-side panels: **Handovers by status** and **Maintenance by state** (small bar or segmented bar charts, no libraries beyond what is already in the repo).
No forms on this page. Fix D5 here too: the "all passed" chip only shows when every operation is passed and there is at least one.

## Phase 4. Handovers screen (`/handovers`)
Purpose: monitor and register handovers.
- Header: title, search, filter chips (status, engineer, date), primary button **New handover** (opens the registration drawer: serial with live Snipe-IT match, ticket, engineer defaulted to the signed-in user; Register; on success go to the case).
- Main view: a board of **columns by progress** (Preparing, Assigned, Paperwork, Done / with gaps) with a card per case: serial, recipient (avatar initials + name), operation strip, age, a stalled badge when stalled. A switch in the header changes the board to a table view (same data, sortable).
- Case page `/handovers/{id}`: keep the lanes and drawer from the previous work, but fix D1, D2, D5: every tile opens a drawer with the controls it needs and each control either works or is disabled with a reason. "Override software check" opens its reason form and sends it. "Push to Snipe-IT" is disabled with a reason until its prerequisite exists, and sends when enabled. "User signed in" gets its control. The printable report is a button "Print form" that is disabled with a reason until the agent report exists. Events appear only on the history page, one human sentence per line.

## Phase 5. Maintenance screen (`/maintenance`)
Terms (owner confirmed): the **vendor ("المورد") is a maintenance company** that repairs devices. Three states: **Needs maintenance**, **In maintenance** (at the vendor), **Returned from maintenance**. Use the HQ Console database model as a reference (vendor, sent date, expected return date, reference number, accessories, condition at send and at return, result, cost, warranty, days at vendor); first read what `maintenance_info` and the governed lists already hold on this branch and extend with a migration only for fields that are missing.
- Header: title, search, vendor filter, primary button **New maintenance** (drawer: serial with Snipe-IT match, reported issue, category, priority, notes; Register puts it in **Needs maintenance**).
- Main view: three columns (kanban) **Needs maintenance / In maintenance / Returned**. Card: serial and model, issue in one line, vendor chip, **days at vendor** with the clock turning amber when it passes that vendor's average turnaround and red when it passes the expected return date, the operation strip. The card's one primary button performs the next step: "Send to vendor" (drawer: vendor from the governed list, reference number, expected return date, accessories sent, condition), "Receive back" (drawer: result, condition, cost, warranty). Each step is an independent, recorded operation; "not done" with a reason is always allowed.
- Vendor panel (right side, collapsible): per vendor, devices currently at the vendor, average turnaround, overdue count; clicking a vendor filters the board. A second tab **At vendors** shows a table of every device currently at a vendor (serial, vendor, sent date, expected date, days, reference).
- Snipe-IT: moving a device between the three states updates the Snipe-IT status label through the existing mapping (env-configured label names). If the label is not configured, show a non-blocking "Snipe-IT status not updated" note and record the operation as not done with that reason.
- Case page `/maintenance/{id}`: same pattern as handovers (passport on the left, tiles, drawer).

## Phase 6. Sync screen (`/sync`) and the agent flow
Goal: the engineer checks a device **without opening the portal on it**. The engineer stays on his own PC in the portal; the employee's PC only runs one short command.
1. `/sync` shows: a big **Start sync** button; after pressing it a large short code (for example `A7-X3-Q9`) with a countdown, a copy button for the one-line command for Windows and one for Linux/macOS (using the portal's real base URL, never `localhost` unless the portal itself is on localhost; use the existing `APP_HOST` setting), and a waiting animation.
2. The device runs the command (existing `static/agent.ps1` / `agent.sh`, no change to what they collect). When the report arrives, the page updates live (poll the existing session endpoint every 2 seconds) and shows the result: serial match check (is it the expected device?), model, OS, RAM, disk, activation, required software ticks and crosses.
3. **Attach to a case**: a selector "Attach to case" (search by serial or recipient, defaults to the open handover or maintenance case with the same serial). Attaching records the report as the Agent report operation (and Software check when the payload has the data) on that case. If the serial matches no case, offer "Create handover" and "Create maintenance" with the serial filled.
4. The Handovers and Maintenance case pages have a "Sync" button on the relevant tile that opens the same flow inside the drawer.
5. Recent syncs (last 10) listed under the button with their result and status.
6. Security stays as designed: the code is short-lived and single-use, only the code-based agent endpoints are reachable without sign-in, the report is bound to the engineer's session, IP binding follows `AGENT_IP_BINDING`. Do not add any new unauthenticated endpoint. If you need one, STOP and write it into `docs/OPEN_QUESTIONS.md`.

## Phase 7. Final verification (all must pass before DONE)
1. `tests/e2e/test_clickthrough.py` green. `pytest` full suite green (the known `test_clipboard_playwright` insecure-origin error: report its exact cause, fix only if it is an environment issue in the test).
2. Screenshots with Playwright at 1440x900 and 390x844, light and dark, of: Dashboard, Handovers (board and table), New handover drawer, a handover case with a drawer open, Maintenance (board and At vendors), New maintenance drawer, a maintenance case, Sync (waiting and result), error page. **Open every screenshot and look.** For each screen write one sentence in the report: what is the focal point, and what the engineer can do in two clicks. Fix anything cropped, overlapping, low contrast, or that looks like a plain admin template.
3. Squint test: shrink each screenshot to 400 px wide; the structure (nav, focal point, groups) must still be readable.
4. Real-data run: with Snipe-IT dev up (`deploy/snipeit-dev`, port 8081) run one `TEST-` handover end to end and one maintenance case through all three states. If Snipe-IT is not available, say `NOT RUN` with the reason.
5. Update `docs/ui/DESIGN.md` (under 400 words, tokens and signature elements), the LIVE GRAPH and the principle files if modules or routes changed, and `HANDOFF.md`.

## Forbidden
Calling something done without the click-through test; links to `/api/...` in pages; buttons that do nothing silently; reusing the old templates just with new colors; new unauthenticated endpoints; weakening CSRF, CSP or role checks; editing or deleting the existing domain tests to make them pass; committing secrets or the HQ Console `.db`, `-wal`, `-shm` files (they contain sessions and password hashes); committing to `main`.

## Final report
Per phase: DONE / PARTIAL / BLOCKED. The table D1 to D9 with how each was fixed and the test that proves it. The click-through test output (counts of pages, links, buttons checked). Screenshot findings sentence per screen. Anything marked `NOT RUN` with the exact reason. New open owner questions.
