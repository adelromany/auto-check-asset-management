# GAP-FIX PROMPT — Handover Portal (apply on top of the already-implemented work)

You are a coding agent. A previous implementation round is already finished in this repository (database, Snipe-IT client, handover workflow, dashboard, 12 principle files in `docs/principles/`). A review against a second design found **specific gaps**. Your job is to close exactly those gaps, nothing else. This is a repair job, not a redesign.

Read this whole document first. Where it is silent, do not invent: record the question in `docs/OPEN_QUESTIONS.md`, take the most conservative option, and continue.

---

## 0. Rules that override everything

1. **Existing behavior is a contract.** Do not rename or move modules, endpoints, tables, columns, or stage keys that already exist. Add; do not replace. Change an existing file only where a task below says so, with the smallest possible edit.
2. **All existing tests stay green after every commit.** Never edit an existing test to make it pass. If one fails: revert your last change and try another way. After two failed attempts on the same step, STOP and report.
3. **One task = one branch = small commits.** Never commit to `main`, `feature/sso`, `feature/shadcn-tailwind-ui`, or any branch from the previous round. Never `git add -A` / `git add .`: stage explicit paths. Never force-push, never merge.
4. **Never invent facts.** Do not guess Snipe-IT fields, file names, or test results. Where this document says "inspect", read the real code. If you cannot verify something, write `UNVERIFIED` in your report and in `docs/principles/09-decisions.md`.
5. **Secrets stay out.** Never open, print, copy, or commit `.env`, tokens, passwords, keys, `data/`, databases, or uploaded files.
6. **Follow H-Caliper** (the 12 files in `docs/principles/`). Obey their rule IDs. Update them as Task 7 says. Never edit a principle silently to match your code: propose it in `09-decisions.md` and say so in your report.
7. **When unsure, STOP and ask.** Never guess what the owner wants.

## 1. Do NOT change (explicit non-goals)

- Do not switch SQLAlchemy between async and sync. Keep what exists.
- Do not move the principle files out of `docs/principles/`. Do not add a `.caliper/` folder.
- Do not change the order of operations that the existing code implements (upload of the signed sheet vs. checkout). Whatever order the code has today stays. If you notice the code and `docs/principles/05-business-principles.md` disagree about it, STOP and report; do not pick one.
- Do not add dependencies. No new packages for any task below.
- Do not touch `static/agent.sh`, `app/auth.py`, or the characterization tests.
- Out of scope: Lab Care, daily reconciliation dashboard, GPO reporting, QR scanning, creating users or assets in Snipe-IT, electronic signatures.

---

## 1A. Facts and constraints inherited from the previous round (from its final report; confirm each by reading the code)

- **Tip of the previous round:** branch `docs/final-sync` (commit `29ec7dd`). Baseline claimed: `284 passed, 7 skipped` for `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py` (the 7 skips: 1 PostgreSQL not exercised, 6 live Snipe-IT tests).
- **Strict Content-Security-Policy (previous Phase 8).** Templates must contain no inline `<script>`, no inline event-handler attributes (`onclick=...`), no inline `style=` attributes and no inline `<style>` blocks. All new JavaScript lives in external files under `static/js/` loaded with `<script src>`; page data is passed through `data-*` attributes or JSON endpoints. After any UI change, load each changed page in a real browser if one is available and check the console for CSP violations; if no browser is available, report `NOT RUN (needs human)`. Never weaken the CSP (no `unsafe-inline`).
- **File size.** `app/services/snipeit_ops.py` (about 640 lines) and `static/js/handover_detail.js` (about 461 lines) already exceed the 400-line guide (CLN-02). Do not grow them beyond a minimal hook (a few lines that import/mount a new module). New logic goes into new modules (for example `app/services/software_check.py`, `static/js/software_check.js`).
- **Known module layout (confirm):** `app/db/models/handover.py`, `app/db/engine.py`, `app/domain/{stages,handover_rules,errors,redaction}.py`, `app/services/{snipeit_ops,documents,dashboard}.py`, `app/clients/snipeit.py`, `app/security/{startup,csrf,headers,ratelimit}.py`, `templates/{handovers,handover_detail,handover_report}.html`, `static/js/{handovers,handover_detail,shell,theme-init}.js`, `static/css/report.css`, `alembic/versions/0001_initial.py` (new revisions are `0002_...`). Reuse `app/domain/redaction.py` for anything about redacting reports.
- **Skipped last time, and NOT actually blocked:** the live Snipe-IT run (Docker Hub pulls timed out), PostgreSQL (`asyncpg` could not be installed), coverage (`pytest-cov` could not be installed), and the Playwright browser matrix. The owner states that Docker Hub and these installs are allowed: retry all of them in Task 0B. If a retry fails, show the exact error and STOP to ask the owner for the specific permission or network access needed (name the exact host, package, or command). Do not simply mark it `NOT RUN`; use `NOT RUN (needs human)` only after the owner replies that it cannot be done. Never disable TLS verification, never use unofficial mirrors, and never add packages outside the approved list to work around a failure.
- **Open questions that stay untouched in this round:** Q-1 (agent session bound to the engineer's handover), Q-2 (meaning of the engineer filter), Q-3 (single-use agent code), Q-4 (rate-limit counters per process).

---

## 2. Task 0 — Inspect and baseline (no code changes)

Do this first and put the results in your first report.

1. `git status`, `git branch -a`, `git log --oneline -15`. Identify the **tip branch of the previous round** (expected: `docs/final-sync`, commit `29ec7dd`; confirm it matches; if the current branch is clean and clearly the latest, use it; if you cannot tell, STOP and ask).
2. Run the full fast suite: `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py`. Record the exact numbers (this is the baseline you must preserve and may only increase). The previous report claimed `284 passed, 7 skipped`; if your numbers differ, report the difference before changing anything.
3. Produce a **name map** of what actually exists (grep, do not assume; section 1A lists the names the previous report gave, confirm each): the file names for stage definitions, status derivation, handover service, repositories, DTOs, routers, templates, JS files, Alembic head revision, and the exact stage keys and their order. Save it in the report. All tasks below say "the stage module", "the service", etc.; use the real names from this map. If something described below does not exist at all in the code, STOP and ask.
4. Confirm these two facts by reading the code, and report the result: (a) how `skipped` is treated today in the status-derivation function and in `can_run`; (b) whether the agent report stored in the database still contains `windows_activation.partial_key` (it must not).

---

## 2A. Task 0B — Real verification that was skipped last time (run before Task 1)

**Branch:** `fix/snipeit-live-verification` (stacked on the tip found in Task 0).

**Why:** every Snipe-IT behavior and the PostgreSQL migration were verified only against a fake or SQLite. Wrong field names would only show up in production. The owner confirms Docker Hub is reachable, so do it now.

1. **Local Snipe-IT.** Follow `deploy/snipeit-dev/README.md`: create the real `deploy/snipeit-dev/.env` from the example (never commit it), run `docker compose up -d`, wait until it is healthy.
   - If an image pull fails, print the exact error once and do **not** retry in a loop. If the cause is network, proxy, registry rate limit, or a permission, STOP and ask the owner for exactly what is needed (for example "allow access to registry-1.docker.io" or "run `docker login`"), then continue after the answer.
   - Snipe-IT needs a first-run setup and an API token. Do whatever the official Snipe-IT documentation allows non-interactively. If a step genuinely needs the web UI, give the owner the exact numbered steps, wait for them to put `SNIPEIT_URL` and `SNIPEIT_TOKEN` into the portal `.env`, and continue. Never print, log, or commit the token.
2. **Seed test data** with names that start with `TEST-` only (assets with serials `TESTSERIAL001..003`, users `test.user1`, `test.user2`). Never touch other records.
3. **Run the live tests** (`SNIPEIT_LIVE_TEST=1`). For every endpoint the client uses, record the REAL request and response shape in `docs/snipeit-api-verified.md` together with the Snipe-IT version. Verify specifically: asset lookup by serial; user search; the checkout payload fields and how `assigned_to` appears afterward; checkin; the asset file upload and the file listing endpoints (and the shape of what the listing returns); `whoami`; and whether Snipe-IT answers some failures with HTTP 200 and a body containing `"status":"error"`.
4. **Every difference between reality and the fake** is a defect: write a failing test first, then fix the client and the fake **together** (never only one). Keep each fix in its own small commit. If a difference changes a business rule or a decision (for example a different attach target), STOP and ask the owner.
5. Test the open decision about attribution: use a personal API token to checkout a `TEST-` asset and read the asset history; record in `docs/snipeit-api-verified.md` whether Snipe-IT shows the token owner or the service account (this answers decision D-12; do not change the design, just record the fact).
6. **PostgreSQL.** Retry installing the driver (`asyncpg`, already an approved dependency) and run the Alembic migrations plus the persistence tests against a real PostgreSQL (for example a throwaway `postgres` container) by setting `TEST_DATABASE_URL`. Fix portability defects with tests first. If the install or container is blocked, apply the same STOP-and-ask rule as above.
7. **Coverage and browsers.** Retry `pytest-cov` and report real coverage numbers (targets in `01-test-principles.md`; do not claim a number you did not see). Retry installing the Playwright browsers and run `tests/test_clipboard_playwright.py`; report the result.
8. Stop the containers when done unless the owner asks to keep them running. Remove nothing that is tracked.
9. Docs in the same branch: `docs/snipeit-api-verified.md`, `docs/OPEN_QUESTIONS.md`, `09-decisions.md` (D-12, D-13 facts), `10-tech-stack-principles.md` (verified versions).

**Done when:** live tests pass (or each failure is explained and awaiting an owner decision), PostgreSQL migration result is reported for real, coverage and Playwright results are reported for real, and the report lists exactly what ran.

---

## 3. Task 1 — Verify the software and Windows activation on the device

**Branch:** `fix/software-verification` (stacked on `fix/snipeit-live-verification`, or on the tip from Task 0 if Task 0B produced no branch).

**Why:** the original pain is engineers forgetting to install or activate things. Today the portal only checks that the agent's serial matches. It must also check the software and activation the agent already reports.

### 3.1 Config
In `app/config.py` (the only place env vars are read) add `REQUIRED_SOFTWARE_IDS` (default `forticlient,sccm,intune,office2021`; parse to a list of lowercase, trimmed, non-empty strings). Add it to `.env.example` with the same default.

### 3.2 Pure rules (domain layer: no I/O, no framework imports)
Add to the stage/rules module:

- `evaluate_hardware(report, expected_serial)` → result with status `passed` only if **all** hold: report serial equals the case serial (trimmed, case-insensitive), `cpu` is non-empty, `ram_gb > 0`, `disks` is a non-empty list. Otherwise `failed`, and the message names **every** problem (for a mismatch: "Serial mismatch: device reports X, case expects Y"). If the existing code already evaluates serial mismatch, extend it; keep its current messages for the cases it already covers.
- `evaluate_software(report, required_ids)` → `passed` only if every required id appears in `software_checks` with `installed == true` **and** `windows_activation.status_code == 1`. Otherwise `failed` with a message listing the missing software names and the activation status text. If `software_checks` is missing or empty: `failed` with "No software checks were reported". Matching of ids is case-insensitive.

Both return a small result object (status, message, detail dict). They never read the clock or the database.

### 3.3 New stage `software_check`
- Add stage key `software_check`, placed **immediately after** `agent_report` in the stage order. It depends on `agent_report`.
- `checkout` must additionally depend on `software_check` being `passed` or `skipped`.
- Treat `skipped` as **satisfied** everywhere a dependency or completion is evaluated: `can_run`, status derivation (`completed` only when every stage is `passed` or `skipped`), `missing_steps` (a skipped stage is not missing). Verify against the real code and fix only what is wrong.
- When an agent report is attached (existing use case), run both `evaluate_hardware` (for the existing `agent_report` stage) and `evaluate_software` (for `software_check`) in the **same transaction**, one event per stage change. If `agent_report` failed because of hardware/serial, `software_check` stays `pending` (do not evaluate software on a report for the wrong device).
- Attaching a new report again (engineer fixed the software and re-ran the agent) must re-evaluate both stages, **unless** `software_check` is already `skipped` by an override (then leave it).

### 3.4 Override (software only)

Implement these use cases in a new service module (for example `app/services/software_check.py`), not inside `snipeit_ops.py`.
- `POST /api/handovers/{id}/software-check/override` body `{ "reason": str }` (length 10–500 after trimming). Allowed only when `software_check` is `failed`. Sets it to `skipped`, stores the reason in the stage detail, writes event `software_check_overridden` with the engineer's email. Any other state → 409 with the current status. **Hardware/serial failures can never be overridden** (there is no endpoint for it).
- `POST /api/handovers/{id}/software-check/reevaluate` (no body): re-runs `evaluate_software` on the latest stored report (for cases that already had a report before this task existed). No report → 409. Writes an event.
- Both endpoints follow the same auth, CSRF, and error-mapping conventions as the existing handover endpoints (inspect one and copy its pattern).

### 3.5 Database migration
Create a **new** Alembic revision (never edit an existing one) that adds the `software_check` stage row for every existing handover:
- handover status `completed` or `cancelled` → insert with status `skipped`, detail message "Added after this case was closed".
- any other status → insert with status `pending`.
Use batch mode as the existing migrations do. The migration must be idempotent (do not insert if a row for that handover and stage exists) and must work on SQLite; it must also run on PostgreSQL (set up in Task 0B through `TEST_DATABASE_URL`); report the result of both.
Creating a **new** handover must create the `software_check` row together with the other stages.

### 3.6 UI and dashboard
- Case page: add the `software_check` item to the stage checklist in its position. Put the new form logic in a new external module (`static/js/software_check.js`) and keep changes to `handover_detail.js` to a minimal hook; no inline scripts or handlers (strict CSP, see 1A). When it is `failed`, show the message and an "Override with reason" form (textarea, 10–500 chars, inline validation, confirmation before submit, loading/disabled state, toast result). When `pending` because the hardware stage failed, show that reason as visible text. Add a "Re-evaluate" button when it is `pending` and a report exists.
- The dashboard "what is missing" column, the per-stage counts, and the stage progress indicator must include the new stage. Terminology on screen: Checkout / Checkin.
- Follow `07-ui-ux-principles.md` (reuse existing classes, `textContent` only, labels, no color-only status).

### 3.7 Tests (new files only)
- Table-driven tests for `evaluate_hardware` and `evaluate_software` (every failure branch; case-insensitive ids; missing `software_checks`; `status_code` 0 vs 1).
- Service tests with the existing Snipe-IT fake: report with everything installed → both stages `passed`; Office missing → `software_check` `failed` and checkout refused with the missing list; override with a 9-char reason rejected (422); override with a valid reason → `skipped`, checkout allowed; hardware mismatch → `software_check` stays `pending` and no override path exists; re-attach after fixing → `passed`; override survives re-attach.
- Migration test on a database that already contains cases in each status.
- API tests: 401 without login, 409 on wrong state, CSRF enforced.
- Existing tests unchanged and green.

### 3.8 Docs in the same branch
`05-business-principles.md` (the stage list, dependencies, BIZ rules for software/override — propose changes via `09-decisions.md` if a rule text must change, then update the file only for the facts that are now true), `03-graph-principles.md` (LIVE GRAPH: new routes, stage, edges; run the graph test), `02-logging-principles.md` (new event types), `09-decisions.md`.

**Known limit to record as UNVERIFIED / open question:** the agent reports Office as id `office2021`. A device with Microsoft 365 will fail this check and need an override. Do not change the agent for this; just record it.

---

## 4. Task 2 — Trustworthy recipient identity

**Branch:** `fix/recipient-identity` (stacked on Task 1).

**Why:** the agent reports the account that runs the script. If an engineer runs it elevated, that is the engineer, not the employee. Capture the interactive (console) user and match on it.

### 4.1 Agent payload (additive, optional)
- In `app/schemas.py` add two optional fields to `AgentPayload`: `user_domain: Optional[str] = None`, `console_user: Optional[str] = None`.
- In `static/agent.ps1` add exactly two assignments next to the existing `username` entry: `user_domain` = `$env:USERDOMAIN`, and `console_user` = the value of `(Get-CimInstance Win32_ComputerSystem).UserName`, wrapped with the safe helper the script already defines near its top. If you cannot do it with two small additions, keep the schema change, skip the script edit, and report it.
- If any existing test fails because of the schema change: revert it and STOP.

### 4.2 Pure function
`detect_recipient(report, engineer_email)` in the domain layer returns `DetectedUser(sam, domain, raw, is_local, same_as_engineer)`:
- Prefer `console_user` (`DOMAIN\sam`); otherwise `username` together with `user_domain`.
- `sam` is lower-cased and has no domain part. `raw` keeps the original string.
- `is_local` is true when the domain is missing or equals the report's `hostname` (case-insensitive).
- `same_as_engineer` is true when `sam` equals the part of `engineer_email` before `@` (case-insensitive).

### 4.3 Wire it in
- When a report is attached, store the detected user (reuse the existing field for the reported username/detected user; add a column only if nothing fits, via a new Alembic revision).
- The recipient search endpoint defaults its query to `sam`. The response additionally carries `is_local` and `same_as_engineer` (additive fields; existing fields unchanged).
- If `is_local` is true or `sam` is empty: do **not** search automatically; the stage stays `blocked` with the message "Cannot determine a domain user on this device — search manually", and the engineer can search by hand (existing manual search path, or add one using the same endpoint with an explicit `q`).
- Confirming a recipient when `same_as_engineer` is true requires the request to carry `acknowledge_same_as_engineer: true`; otherwise 409 with a clear message. Confirmation still records who confirmed and when.
- The detected user stays an **untrusted assertion**: no Snipe-IT write uses it until the engineer confirms a Snipe-IT user.

### 4.4 UI
Show "Detected on device: DOMAIN\sam" and the Snipe-IT match side by side, a visible warning when `same_as_engineer` (with an acknowledge checkbox next to Confirm), and the blocked message with a manual search box when `is_local`.

### 4.5 Tests
Table-driven `detect_recipient` tests (console user present; console user empty; only username+domain; local account; same as engineer; mixed case; domain prefix stripped). Service tests: elevated-run scenario (reported user equals the engineer) → warning, confirm refused without acknowledgement, allowed with it; local account → blocked and no Snipe-IT call made; manual search works. Existing tests green.

### 4.6 Docs
`04-security-principles.md` (SEC-06 wording stays; add how the console user improves, not proves, identity — via `09-decisions.md` proposal if rule text changes), `05`, `03` (graph), `09`.

---

## 5. Task 3 — Printable sheet: no invented legal text

**Branch:** `fix/sheet-legal-placeholder` (stacked on Task 2).

Inspect the printable report (expected: `templates/handover_report.html`, `static/css/report.css`, served by the report endpoint under `/api/handovers/{id}/report`; confirm the real names and keep the existing route). It must contain, in this order: its existing title (do not rename it), case code, date, device details (serial, manufacturer, model, CPU, RAM, disks with size and type, OS) taken from the stored report **without the Windows product key**, recipient and engineer names, a clearly marked block with the literal text `[Company legal text goes here]`, signature lines for the recipient and the engineer, and the case code again at the bottom. **Remove any legal or policy wording that the previous round wrote itself** and replace it with that placeholder block; legal wording must come from the owner. Printing rules: A4, black on white, no navigation or buttons (`@media print`).
Tests: the sheet contains the serial, case code, and the placeholder; contains no product key; the page returns 409 (or the existing behavior) when no report exists. Docs: `07`, `05`, `09` (record "legal text supplied by owner" as an open item).

---

## 6. Task 4 — Timezone-safe datetimes (SQLite returns naive values)

**Branch:** `fix/datetime-utc` (stacked on Task 3).

SQLite returns timezone-naive datetimes even for `DateTime(timezone=True)`. Comparing them with aware values raises errors or gives wrong results (for example in time-to-complete and age calculations).
1. Grep every place that compares or subtracts datetimes read from the database (services, dashboard, domain functions, templates/JS formatting).
2. Add one helper `as_utc(dt)` (naive → treated as UTC and made aware; aware → converted to UTC; `None` → `None`) in one shared module (inspect where utility code lives; if nowhere, `app/domain/timeutil.py`, standard library only). Use it at **every** such comparison. Do not scatter ad-hoc `replace(tzinfo=...)` calls.
3. Regression tests first: reproduce the failure with a record read back from a temporary SQLite file, then fix. Cover: time-to-complete average on the dashboard, age-based comparisons, and the helper itself (naive, aware non-UTC, None).
Docs: `11-clean-code-principles.md` (add the rule; propose via `09` if it needs a new ID), `09`.

---

## 7. Task 5 — Stalled by age (configurable)

**Branch:** `feature/stall-by-age` (stacked on Task 4).

**Why:** a case nobody touches should surface as stalled even if no stage failed.
1. `app/config.py`: `STALL_HOURS` (default `24`; `0` disables the rule). Add to `.env.example`.
2. Status derivation (pure, clock passed in): in addition to the current rule, a case whose status is not terminal (`completed`, `cancelled`) and whose last update is older than `STALL_HOURS` is `stalled`. `missing_steps` is unchanged; add one short human sentence to the case view: "No activity for N hours" when the age rule applies.
3. Dashboard: counts and list filters must treat "stalled by age" as `stalled`. Implement with SQL conditions (`status IN ('draft','in_progress') AND updated_at < cutoff`), **not** by loading every row into Python. Use `as_utc` and an injected `now`. Keep pagination caps.
4. Record in `09-decisions.md` as **PROPOSED** (the owner has not confirmed the threshold): "Stall threshold 24h, configurable, 0 disables." Add the question to `docs/OPEN_QUESTIONS.md`.
5. Tests: fake clock; boundary (exactly at the threshold vs. just over); disabled with `0`; terminal cases never stalled by age; dashboard summary and list filter agree with each other; query count for the list endpoint unchanged.
Docs: `05` (BIZ rule text only after proposal accepted by the owner — until then describe it as proposed), `12-performance-principles.md` (no new table scans), `03`, `09`.

---

## 7A. Task 5A — Technical logging with request ids

**Branch:** `feature/structured-logging` (stacked on Task 5).

**Why:** the previous report says request ids and structured technical logging were not built (open question Q-5), although `02-logging-principles.md` requires them (LOG-02, LOG-03, LOG-08, LOG-10). The `events` audit trail already exists and does not change.

1. Inspect what logging exists today (`grep -rn "logging" app`). Create or extend `app/logging_config.py` (standard library only): one `configure_logging()` that is safe to call twice (no duplicate handlers); level from `LOG_LEVEL` in `app/config.py` (default `INFO`; add it to `.env.example`); one-line `key=value` format with a UTC timestamp, level, logger name and `request_id`.
2. Request id: a middleware generates a short id per request on the server (never trust a client-supplied one), keeps it in a `contextvars.ContextVar`, returns it in the `X-Request-ID` response header, and a logging filter adds it to every log record. Register it as the outermost middleware and confirm the CSP/security-headers/CSRF middlewares still work (run the full suite).
3. The generic 500 handler returns the `request_id` in the JSON body and no stack trace; the stack trace goes to the log only (LOG-08). Do not change status codes or existing error shapes beyond this added field.
4. Startup logs one INFO line with the non-secret configuration summary (database dialect, SSO on/off, Snipe-IT host) and a WARNING when `SSO_ENABLED=false` (LOG-10). Never log secrets (LOG-05).
5. The Snipe-IT client logs target, operation, status and duration only (LOG-09). Verify an existing test asserts the token never appears in logs; add one if missing.
6. Tests: header present and different per request; log records carry the request id (`caplog`); 500 body contains the id and no traceback text; token absent from captured logs; calling `configure_logging()` twice does not duplicate output; existing tests unchanged.
7. Docs: `02-logging-principles.md`, `03-graph-principles.md` (new module and relation), `09-decisions.md`, `docs/OPEN_QUESTIONS.md` (close Q-5).

---

## 8. Task 6 — Re-check the previously claimed items (inspection only; fix only if broken)

**Branch:** only if a fix is needed: `fix/<short-name>` (stacked on Task 5). Otherwise no branch, just report.

A `docs/security-review.md` already exists from the previous round: start from it and verify its claims; do not rewrite it. Verify by reading code and running tests, and report each as OK / FIXED / BROKEN-NEEDS-OWNER:
1. Agent reports stored in the database contain no `partial_key`; logs never contain tokens or full agent payloads (a test exists and passes).
2. Checkout is idempotent: a second call when the stage is already `passed` makes **no** Snipe-IT call; an asset already assigned to the confirmed recipient is marked `passed` without a write; an asset assigned to someone else fails with the holder named and no write; the result is verified by re-reading the asset.
3. State-changing session-authenticated routes enforce the CSRF token and `Origin` check; security headers are present; the application refuses to start with an empty or `change-me` `SESSION_SECRET` when SSO is enabled.
4. `events` has no update/delete method; every state change writes an event with the engineer's email.
5. Uploads: magic-byte check, size cap, random stored name, never served statically, authenticated download.
Fix only genuine defects, each with a failing test first. If a defect needs a decision, STOP and ask.

---

## 9. Task 7 — Final documentation sync

**Branch:** `docs/gap-fix-sync` (stacked on the last branch used).

1. `03-graph-principles.md`: rebuild the LIVE GRAPH from the code as it is now (new routes, stage, events, config keys, modules). Run `python -m pytest tests/test_graph_consistency.py` and the architecture-rules test; both must pass. This file is the most important.
2. `09-decisions.md`: one entry per decision or deviation made in these tasks (including every PROPOSED and UNVERIFIED item). Only the owner changes a status to accepted.
3. `02-logging-principles.md`: the event catalog must equal the event types the code actually writes (`grep -rn "event_type" app`).
4. `01-test-principles.md`: current commands, test counts, list of test files by purpose.
5. `04`, `05`, `06`, `07`, `08`, `10`, `11`, `12`: correct only what no longer matches reality; add no aspirational rules.
6. `README.md`: stage list, new config keys, new endpoints, how to run migrations.
7. `docs/OPEN_QUESTIONS.md`: Office 365 detection; stall threshold; legal text for the sheet; upload-before-checkout order (if any disagreement was found in Task 0); attribution of Snipe-IT writes (still open). Mark Q-5 closed if Task 5A was done; leave Q-1 to Q-4 untouched.

---

## 9A. Optional tasks (start ONLY when the owner writes the exact trigger phrase)

- **"go refactor"** → branch `refactor/split-large-modules`. Split `app/services/snipeit_ops.py` and `static/js/handover_detail.js` into modules of at most 400 lines by responsibility. No behavior change, no renamed endpoints, no edits to existing tests; the full suite must show the same pass count; update the graph. One extracted module per commit.
- **"go perf"** → branch `feature/performance-check`. Add `scripts/seed_perf.py` (dev only, SQLite, 10,000 handovers with stages and events, created through the repositories) and `docs/performance-notes.md` with measured p95 timings of the list endpoint and the dashboard summary against the targets in `12-performance-principles.md` (machine and date included), plus a query-count test for the list endpoint and the case page. If targets are missed, say so and open an entry in `docs/OPEN_QUESTIONS.md`.
- **PostgreSQL** is handled in Task 0B and is re-run after every new migration in this round. Never report it as passed unless it actually ran.

---

## 10. Phase report (print after every task, exactly this format)

```
TASK REPORT <number> <name>
Branch: <name> (stacked on <previous>)
Commits: <short hashes + messages>
Files created: <list>
Files edited: <list>
Commands run and real results: <command -> summary>
Tests: <N> passed, <N> failed (baseline was <N>; failed must be 0)
Documents updated: <list>
UNVERIFIED items: <list or none>
Deviations from this prompt: <list or none>
Questions for the human: <list or none>
```
Never claim a result you did not see. If something could not run (no Docker, no PostgreSQL, no browsers), write `NOT RUN (needs human)` and say why.

## 11. Stop conditions (stop, report, wait)

An existing test fails twice after your fixes · a task needs a file or behavior this document told you not to change · code and a principle file contradict each other · something described here does not exist in the code · you find a secret in a tracked file (report the file name only) · you are unsure what the owner wants.

## 12. Forbidden (checked in review)

`git add -A`, `git add .`, force-push, merging, commits to protected or previous-round branches · new dependencies · `innerHTML` with data · SQL built from strings · logging tokens, passwords, product keys, uploaded content, or full agent payloads · editing generated CSS by hand (run `npm run build:css` and commit the result if you changed styles/templates) · changing existing endpoint paths or response shapes (additive fields only) · inventing legal text, Snipe-IT fields, or test results.

Start with Task 0. Report before continuing to Task 1.
