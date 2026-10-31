# Task: Make the Handover Portal ready to be hosted on a server (engineer access model, concurrent onboardings, better search, new branding)

Repo: `auto-check-asset-management`. Start from the tip of branch `docs/deployment-guide`. Create ONE branch per part, each stacked on the previous (names in each part). Never commit to `main`. No force-push. No new runtime dependencies without asking. Follow all 12 principle files (Security, Business, Architecture, Clean Code, Tests, Git, Decisions, Graph).

## 0. Rules (override everything)
1. Tests first for every behavior change. Never delete or weaken an existing test to make it pass; if an old test encodes behavior that this task deliberately changes, change that test in the same commit and say why in the commit message.
2. Layering stays: routers, then services, then repositories/clients, then db/external; `app/domain` stays pure. The architecture tests and `tests/test_graph_consistency.py` must stay green. Update the LIVE GRAPH for every new module.
3. Do not touch `static/agent.sh` behavior except what a part explicitly says. Do not change `app/auth.py` login flow except in Part 1. Do not touch `tests/test_characterization.py` (if a part forces a change there, STOP and ask).
4. Secrets never printed, logged, or committed. No personal data in logs (log ids, not names/emails).
5. Every claim in your report must come from a command you ran. If something cannot run (no PostgreSQL, no browser), say `NOT RUN` with the exact error. Never write "should work".
6. Anything you decide that the owner did not decide goes into `docs/principles/09-decisions` as `PROPOSED` and into `docs/OPEN_QUESTIONS.md`. Do not present proposals as final.
7. Commit after each numbered step. Run the full suite before each part's last commit and report exact counts.

## 1. Inspect first (no changes)
Read and summarize in your notes (do not skip): `app/main.py`, `app/dependencies.py`, `app/config.py`, `app/auth.py`, `app/routers/{pages,agent,handovers,dashboard,documents,snipeit}.py`, `app/services/{sessions,handovers,dashboard,snipeit_ops}.py`, `app/repositories/handovers.py`, `app/db/models/handover.py`, `app/security/*.py`, `app/schemas.py`, `static/app.js` (how the agent command is built), `static/agent.ps1`, `templates/{index,handovers,handover_detail}.html`, `templates/partials/*`, `static/js/handovers.js`, `docs/security-review.md`, `docs/OPEN_QUESTIONS.md`. Run the suite and record the baseline counts. If the baseline is red, report the numbers and fix nothing unrelated.

## 2. Context (facts verified in the code; confirm each by reading)
- Agent flow: browser calls `/api/session/new` (SSO required), a 6-character code is created in an **in-memory** `SessionStore` (`app/services/sessions.py`, uses `random`, not `secrets`), the agent POSTs to `/api/session/{code}/submit` with no login (the code is the secret), the browser polls `/api/session/{code}/data`.
- The store is per process: with more than one server worker, a code created in one worker is unknown to another, and a restart loses all codes.
- There are no roles: any signed-in user can do everything. Handover create/update routes are protected by CSRF; the agent submit route is rate-limited (60/min per client address, in memory).
- One active handover per device serial is enforced by a partial unique index.
- The "Handover cases" list filters by status, engineer (exact email match), and created date only.
- Branding: `FastAPI(title="Snipe-IT Onboarding")`, `templates/partials/logo.html` (monitor with a check mark, default title "Snipe-IT Onboarding"), `static/favicon.svg`, `docs/logo.svg`, agent scripts print "Snipe-IT Onboarding Agent".

---

# PART 1: Access model on one hosted server
Branch: `feature/hosted-access-model`.

## 1.1 Who uses the hosted portal (the real situation, confirmed by the owner)
The portal runs on a server. **Everyone who opens it in a browser is an IT engineer or a manager signed in with Microsoft Entra SSO.** There is no employee-facing web page.

During an onboarding, the engineer physically sits at (or remotely uses) the **employee's PC**, opens the portal in the browser **on that PC** (using the server's address), and signs in with the **engineer's own** account. The Windows account logged on to that PC is the **employee's** (this is the future recipient of the device). The engineer then copies the agent command from the portal and runs it in PowerShell on the same PC; the script reports the PC's data back to the portal.

| | Dashboard use (anywhere) | Onboarding use (engineer at the employee's PC) |
|---|---|---|
| Who | Manager or team member | The engineer |
| Browser identity | Their own SSO account | The ENGINEER's SSO account, even though the PC belongs to the employee |
| Windows user on that PC | n/a | The employee (not the engineer) |
| The PowerShell script | n/a | Has no browser cookie and no login: the one-time session code is its only credential |

Consequences you must implement:
1. The PowerShell script is the only unauthenticated client. Everything else requires SSO and a role.
2. The agent detects the Windows user as the **recipient candidate** (never as the engineer). The engineer's identity always comes from the SSO session, never from the script. Keep the existing "same as engineer" safeguard (engineer must acknowledge if the detected user equals the engineer).
3. The engineer's SSO session now lives in a browser on someone else's computer. That is a security risk you must reduce (see 1.5).
4. Since the browser opens the portal by the server's address, `window.location.origin` is already the right origin for the agent command. Verify that; do not add a new required URL setting for it.

## 1.2 Roles from Entra groups (decided by the owner)
Roles: `viewer` (read dashboard, search, open case pages, view reports), `engineer` (viewer plus create handovers, generate agent codes, confirm recipient, checkout/checkin, upload and push documents, software override on own handovers), `manager` (engineer plus act on other engineers' handovers, cancel any handover).
1. Configuration in `app/config.py` only: `ENTRA_GROUP_VIEWER`, `ENTRA_GROUP_ENGINEER`, `ENTRA_GROUP_MANAGER` (each is the group's **object ID**, a GUID; any may be empty = unused). Highest matching role wins. A signed-in user who is in none of the groups gets **no access** (HTTP 403 page "You are not authorized to use Handover Portal. Ask IT to add you to the right group."). In dev mode (`SSO_ENABLED=false`) the dev user is `manager`.
2. In `app/auth.py` callback: read the `groups` claim from the ID token (the app registration must have the groups claim enabled; document the exact Azure steps: App registration, Token configuration, Add groups claim, "Groups assigned to the application" is recommended so the token stays small). Store ONLY the list of group IDs that match the three configured IDs (not all groups) in the signed session, together with name and email. The cookie is signed; still recompute the role from the stored matching groups and the current config on every request.
3. **Group overage:** if the token has no `groups` claim but has the overage marker (`_claim_names` containing `groups`), fail closed: no access, a clear log line without personal data (`groups_overage`), and the 403 page tells the user to ask IT. Do not call Microsoft Graph in this task. Document the cause and the fix (assign groups to the application).
4. A pure function `role_for(group_ids, config_ids) -> Role | None` in `app/domain/` (no framework imports); a dependency `require_role(minimum)` in `app/dependencies.py`.
5. Apply to every route: all `POST/PUT/PATCH/DELETE` under `/api/handovers` need at least `engineer`; acting on a handover whose `engineer_email` differs from the caller needs `manager`; every read needs at least `viewer`; pages redirect to login or show the 403 page.
6. `GET /api/me` returns `{name, email, role}`. The UI hides or disables what the user cannot do; the server enforces regardless.
7. Tests: a matrix over every route and every role; no-group user gets 403 everywhere; overage fails closed; highest role wins; empty group config means that role is unused; changing config changes the result; dev user is manager; the stored session never contains non-matching group IDs.

## 1.3 Make the PowerShell-script surface tiny and safe
1. Exactly these paths are reachable without SSO: `/static/*` (including `agent.ps1` and `agent.sh`), `POST /api/session/{code}/submit`, `GET /health` (minimal body, no versions or secrets). The login/callback/logout routes are the only other exceptions. Write a test that enumerates every route in the app and fails if any other route works without a session when `SSO_ENABLED=true`. Keep that test in the suite so a new route cannot accidentally become public.
2. Replace the in-memory session store with a **database-backed** store (new table `agent_sessions`, Alembic revision, SQLite and PostgreSQL compatible). Columns: id, `code_hash` (SHA-256 of the code, unique; never store the plain code), `handover_id` (nullable for the legacy standalone page), `engineer_email`, `status` (`waiting`, `submitted`, `expired`, `superseded`), `created_at`, `expires_at`, `submitted_at`, `payload` (redacted JSON, nullable; for sessions with no handover it is purged at expiry). Keep the `SessionStore` public methods (`create`, `get`, `submit`, `purge_expired`, `active_count`) or an equivalent injected interface so the routers change minimally. Keep the in-memory implementation for unit tests if the existing tests rely on it, behind the same interface.
3. Code generation: use `secrets`, not `random`. Alphabet without look-alike characters (no `0 O 1 I L`), 12 characters shown as `XXXX-XXXX-XXXX` (about 58 bits). The engineer copies the command, so length costs nothing. Lookup is by hash; compare with constant time where applicable. Accept the code case-insensitively and ignore dashes. Update `static/app.js` / templates only where the displayed code format is asserted.
4. Single use, atomic: the submit path does one conditional update (`UPDATE ... SET status='submitted' WHERE code_hash=? AND status='waiting' AND expires_at > now`) and checks the affected row count. Two simultaneous submits of the same code: exactly one wins, the other gets `already_submitted` (HTTP 200 idempotent, as today, and it must not overwrite the stored payload).
5. One waiting session per handover: creating a new code for a handover marks any earlier waiting code of that handover `superseded` (partial unique index on `(handover_id)` where `status='waiting'`, plus the logic). A superseded or expired code answers 404 to the agent with the same body as an unknown code (no oracle).
6. Unknown, expired, superseded and wrong codes all return the same 404 and the same response time class. Add a failed-attempt limiter keyed by client address: more than N unknown codes in a window returns 429 with `Retry-After` (config `RATE_LIMIT_BAD_CODE_PER_WINDOW`, default 20). The existing submit limiter stays.
7. Binding: the session record is bound to its handover and its creating engineer. Polling is allowed only to the creating engineer or a manager. The agent's report goes through the existing `record_agent_report` (which fails the stage when the reported serial differs from the handover's serial).
7a. **Same-machine binding (new, PROPOSED):** the engineer's browser and the PowerShell script run on the same PC, so they normally share one source IP address. Store the client address of the request that created the code (`created_from_ip`, column in `agent_sessions`) and compare it with the address of the submit request. Config `AGENT_IP_BINDING` with values `off`, `warn`, `enforce`; default `warn`. `warn` accepts the report but records an event (`agent_ip_mismatch`) and shows a notice on the case page ("The report came from a different address than this browser; confirm you ran the command on the right PC"). `enforce` rejects with the same 404 body as an unknown code. The client address comes from the direct peer, or from `X-Forwarded-For` only when the peer is in `TRUSTED_PROXIES` (config list, default empty). Tests for off/warn/enforce, with and without a trusted proxy, and for a spoofed header from an untrusted peer.
8. Payload safety on the public endpoint: keep the pydantic model strict; add a maximum body size (reject over 64 KB with 413), reject unknown huge strings, keep redaction before storage. Tests with oversized and malformed bodies.
9. Purge: expired sessions are removed lazily on create/get and by a small function callable from startup; never block a request for long. Test it.
10. Docs: update `docs/security-review.md` (what the device surface is, what the code protects, what it does not), answer Q-3 (single-use and handover-bound) and Q-4 (per-process limiter: document that a multi-worker deployment needs a shared store or a proxy-level limit; implement the proxy guidance in the deployment guide).

## 1.4 Hosted mode basics (TLS is OUT OF SCOPE for now, by owner decision)
1. Do not add HTTPS enforcement, TLS startup checks, or certificate work. Keep `HTTPS_ONLY` working as it does today. Do not weaken it either. The deployment guide gets one sentence: "TLS is not configured yet; the portal currently runs over HTTP on the internal network. Add TLS before exposing it more widely."
2. Verify, with a test and with a real run through the server's hostname (not `localhost`): the CSRF origin check accepts the server's own origin (`APP_HOST`), the agent command uses the server's address, and the session cookie works. If `APP_HOST` is wrong or missing, the UI shows a clear warning instead of a broken command.
3. Startup validation (`app/security/startup.py`): refuse to start in hosted mode when `SESSION_SECRET` is default/short, or when `SSO_ENABLED=false` while listening on a non-loopback address (message says what to set). Tests.
4. Trusted proxies: only needed for 1.3 item 7a and the rate limiters; implement `TRUSTED_PROXIES` as described there. Document a reverse-proxy example as optional and mark it `NOT VERIFIED` if you did not run it.
5. Network rule for the deployment guide (no code): the employees' PCs must be able to reach the portal address; document which paths the PowerShell script needs (`/static/agent.ps1`, `/api/session/<code>/submit`).

## 1.5 The engineer's login on someone else's PC
1. Login: pass `prompt=select_account` when redirecting to Entra, so a browser that still holds a previous engineer's Microsoft session does not sign in silently as that person. Test that the parameter is sent.
2. Logout: `/logout` clears the portal session AND redirects to the Entra end-session endpoint (`https://login.microsoftonline.com/<tenant>/oauth2/v2.0/logout` with `post_logout_redirect_uri` = the portal's login-free landing page), so the Microsoft session on that PC is closed too. The post-logout URL must be registered in Azure: add it to the deployment guide and to `docs/OPEN_QUESTIONS.md`. If the setting is missing, fall back to the local logout and log one warning.
3. A visible "Sign out" button in the top bar on every page, and after the last stage of a handover (document pushed) a clear panel: "Done. Sign out of this PC now" with the button. The case page also shows the signed-in engineer's name at all times.
4. Session lifetime: add `SESSION_MAX_AGE_SECONDS` (default 3600; today it is hardcoded) and an idle timeout `SESSION_IDLE_SECONDS` (default 1800) enforced server-side by storing the last-activity time in the session. Tests with a fake clock.
5. Docs: engineers should use a private/InPrivate window on an employee's PC and close it at the end. Put that in the deployment guide and in the top of the onboarding page as one short line.
6. Never put the engineer's email or token into the agent command, the agent payload, or anything stored on the employee's PC. Check `static/agent.ps1` output and temp files; report what it leaves on disk (it should leave nothing).

# PART 2: Several onboardings at the same time
Branch: `fix/concurrent-onboarding`, stacked on Part 1.

## 2.1 What "at the same time" means here (scenarios to make safe and to test)
| # | Scenario | Required result |
|---|---|---|
| S1 | Two different devices, two engineers (or one engineer), at the same moment | Fully independent: two handovers, two codes, each report lands only on its own handover |
| S2 | Two engineers create a handover for the SAME serial at the same moment | Exactly one is created; the other gets HTTP 409 with a message naming the existing handover (id and owner name) and a link |
| S3 | Same handover, "generate command" clicked twice (or in two tabs) | Only the newest code works; the older one is superseded; the UI shows the newest code |
| S4 | Same code submitted twice at the same moment (agent run twice) | One report stored; second call is `already_submitted`; no duplicate rows, no overwritten payload |
| S5 | Agent run with the wrong code (typed or pasted from another device) | The report goes to the other handover's session. The stage compares serial numbers, so that handover's agent stage fails with the existing serial-mismatch reason, the event trail records it, and the engineer sees "Wrong device: ask for a new code" with a button to generate a new code. Never silently accept. The other device's onboarding is not corrupted: its stage can be re-run with a new code |
| S6 | Two engineers click checkout (or confirm recipient, or push document) on the same handover at the same moment | One Snipe-IT write only; the second request sees the finished state and returns an idempotent success or a clear 409; no double checkout, no double upload |
| S7 | Many onboardings at once (load) | No errors, no cross-talk, no lost updates, no deadlocks |
| S8 | Server restarts during an onboarding | Handover state survives (database); a waiting code survives if still within 10 minutes (database-backed store) |

## 2.2 Implementation
1. S2: catch the unique-index violation when creating a handover (do not rely only on a pre-check query); translate to a domain error `ActiveHandoverExists(existing_id, engineer_name)` and HTTP 409. The pre-check stays for a friendlier message. UI shows the message with a link to the existing case.
2. S3: covered by Part 1 (one waiting session per handover); add the UI behavior (new code replaces the old one, old command is visibly marked "replaced").
3. S4: covered by the atomic update in Part 1; add the tests below.
4. S5: add the "Wrong device" message to the case page when the agent stage failed with the serial-mismatch reason, and an easy "Generate new code" action. Add an event type for it. Do not change the failure rule itself.
5. S6: add row-level protection in the service layer for every operation that writes to Snipe-IT or changes a stage: `SELECT ... FOR UPDATE` on the handover row on PostgreSQL (SQLAlchemy `with_for_update()`), and on SQLite rely on its single-writer lock with a busy timeout (set `PRAGMA busy_timeout` and WAL mode through the engine setup in `app/db/engine.py`). Re-read the handover state AFTER taking the lock, then decide (checkout already assigned to the same user means mark passed without writing, as today). Keep the existing idempotency.
6. S7/S8: make sure no module-level mutable state is shared between requests (search `app/` for module-level dicts, lists, caches; report each and either remove it or justify it in the docs). The Snipe-IT client is created per request already; keep it that way. Check the database pool settings for PostgreSQL (`pool_size`, `max_overflow`, `pool_pre_ping=True`) and set sensible, configurable defaults.
7. **Database for the hosted server is PostgreSQL (decided; do not ask).** Facts: the current local copy runs on SQLite (`data/handover.db`, no `DATABASE_URL` in `.env`); the code supports PostgreSQL through `asyncpg` but the earlier rounds could not run it. Make it real now: install the already-approved `asyncpg`, start a throwaway PostgreSQL container (Docker Hub is allowed; if a pull is refused, show the exact error and STOP to ask for the permission), run `alembic upgrade head` on it, run the FULL test suite against it with `TEST_DATABASE_URL`, and fix every portability defect with tests first. Add `deploy/postgres-dev/docker-compose.yml` (dev only, random password from `.env`, port 5433) and a documented `DATABASE_URL` example in `.env.example` and the deployment guide. SQLite stays supported for tests and single-PC development. When `DATABASE_URL` is SQLite and the process looks like a hosted run (non-loopback host or more than one worker), log a startup WARNING that PostgreSQL is required there. Do not block startup. Report the PostgreSQL results separately and honestly.

## 2.3 Tests (all must be deterministic; no sleeps)
Use `asyncio.gather` against the ASGI app (httpx `AsyncClient` with the app) or the service layer. Write one test per scenario S1 to S8 (S8 by recreating the app/engine against the same database file). Each test asserts the exact table contents afterwards (number of handovers, sessions, reports, events, stage statuses) and, for S6, the number of Snipe-IT calls recorded by the fake. Add one load-style test: 25 simultaneous onboardings with distinct serials and codes; assert 25 handovers, 25 reports, each report's serial equals its handover's serial, zero 5xx. If PostgreSQL is available (`TEST_DATABASE_URL`), run the same concurrency tests on PostgreSQL and report both results; if not, report `NOT RUN (PostgreSQL)` with the reason.

---

# PART 3: Search by recipient and by device serial
Branch: `feature/handover-search`, stacked on Part 2.

## 3.1 Behavior
On the Handover cases page add these filters, working together with the existing ones (status, engineer, dates) as AND:
1. **Recipient**: one text field. Matches, case-insensitive and by substring, any of: the recipient's full name, Snipe-IT username, email, and the username the agent reported. 
2. **Device serial**: one text field. Matches, case-insensitive and by substring, the device serial and the Snipe-IT asset tag.
3. **Engineer**: change the existing exact-email match to a case-insensitive substring match over engineer name and email (this also answers open question Q-2). The datalist suggestions stay.
4. Minimum 2 characters to filter by a text field (shorter input is ignored with a visible hint); maximum 100; trim whitespace; treat `%`, `_` and backslash as literal characters (escape them) so a search for `%` does not match everything.

## 3.2 Data (migration required)
Today the handover stores `recipient_snipeit_id` and `recipient_snipeit_username` only, so the recipient's name and email cannot be searched. Add nullable columns `recipient_snipeit_name` and `recipient_snipeit_email` (Alembic revision, upgrade and downgrade tested on SQLite; PostgreSQL if available). Fill them when the engineer confirms the recipient (the Snipe-IT user lookup already returns name and email; read `docs/snipeit-api-verified.md` for the real field names, do not guess). Existing rows stay null and are still found by username. Apply the same data minimization as the rest of the app: no email or name in logs; the redaction rules and the security review are updated to list these two fields as personal data stored on purpose.

## 3.3 Implementation
1. Repository (`app/repositories/handovers.py`, and the dashboard query path in `app/services/dashboard.py`): add `recipient` and `serial` (and the engineer change) as parameters of ONE shared filter-building function used by both the list API and the server-rendered page, so the two cannot drift apart. Use SQLAlchemy expressions with bound parameters only (`func.lower(col).like(pattern, escape="\\")`); never string-build SQL.
2. Router: new optional query parameters `recipient` and `serial` on the list endpoint with length validation (422 on violation). Keep every existing parameter and response shape (additive change only).
3. The dashboard rows already show the device; make sure the recipient column shows the recipient name (fallback: username, then "not set") and the serial column is visible, so the user sees why a row matched. Highlight the matched text in the cell (client side, using `textContent` and DOM nodes only, never `innerHTML`).
4. UI (`templates/handovers.html`, `static/js/handovers.js`): two new inputs with visible labels ("Recipient", "Device serial"), placeholders, debounce 300 ms, request cancellation of the previous in-flight request, filters mirrored in the URL query string (a filtered view can be bookmarked and shared; opening such a URL applies the filters on load, including on the server-rendered first paint), a "Clear filters" button, active-filter chips, a result count, and a friendly empty state ("No cases match these filters"). Keyboard accessible, works in dark mode and at 390 px width. Do not break the strict CSP (no inline scripts or styles).
5. Performance: add indexes only where useful and portable: an index on `lower(device_serial)` is not portable across SQLite and PostgreSQL in the same way; instead keep the existing `device_serial` index and document that substring search is a scan, acceptable for the expected volume. Add a test or a note with the measured time for 10,000 seeded rows (use or create `scripts/seed_perf.py`); report the number you measured.

## 3.4 Tests
Unit and API tests: recipient by name, by username, by email, by reported username; serial by full and partial value; serial by asset tag; case-insensitivity; wildcard characters treated literally; 1-character input ignored; 101 characters rejected; combination with status, engineer, and dates; pagination and total count stay correct with filters; page and API return the same rows for the same filters; null recipient columns do not break search; SQL injection strings (`' OR 1=1 --`) return normal "no match" results. A browser test (Playwright; `NOT RUN` with the error if it cannot launch) that types in the fields, sees the list update, copies the URL, reloads, and sees the same filtered result.

---

# PART 4: Branding: the app is "Handover Portal" with the b_labs logo
Branch: `feature/branding-handover-portal`, stacked on Part 3.

## 4.1 Facts and the logo file
The owner wants the **existing b_labs image** as the application logo, replacing the monitor-with-check icon, and the application name **Handover Portal** everywhere instead of "Snipe-IT Onboarding".
1. Search the repository and the working tree (every extension: svg, png, jpg, jpeg, webp, ico; names containing `b_labs`, `blabs`, `b-labs`, `logo`) for the b_labs image. At the time of writing no such file is committed.
2. The owner confirms the b_labs image EXISTS on their machine but was **not pushed to GitHub**, so you will most likely not find it. If it is NOT found: do the text renaming in 4.3 and the logo slot in 4.2 (point to `static/img/b_labs.svg`, with a graceful fallback to the text name only), then STOP this part and tell the owner exactly what to do: "Copy the b_labs image to `static/img/` (name it `b_labs.svg`, or `b_labs.png` at least 512 px wide with a transparent background, plus `b_labs-dark.*` if a dark version exists), commit it, push the branch, and tell me." Do not invent, trace, redraw, or approximate a logo, and do not download one from the internet.
3. If it is found: use it as is. Do not recolor or distort it. Keep the aspect ratio.

## 4.2 Where the logo goes
1. `templates/partials/logo.html`: replace the drawn monitor icon by the image. Keep the macro names (`logo_mark`, `logo_lockup`) so templates do not change; add `alt="B_Labs"` on the mark when it is used alone and an empty `alt` when the visible name is next to it. Size: a fixed height (about 32 px in the top bar), width auto, no stretching, no rounded crop unless the logo itself is round. Provide a light and a dark variant if the file has both; if there is one file only, check it is readable on both backgrounds and put it on a neutral rounded tile if needed (report which one you did).
2. Favicon: generate `static/favicon.svg` or `favicon.png/ico` from the same logo (only from the supplied file; no redrawing). Update `<link rel="icon">` in `page_head.html` and `index.html`.
3. Also use it on: the login/redirect page if any, the printable handover report header (`templates/handover_report.html`; it must work in print and in black and white), and the README header.
4. The strict CSP must still pass: the image is served from `/static/img/` (same origin), no inline data URIs unless the CSP already allows them.

## 4.3 The name
Search the whole repo (code, templates, JS, agent scripts, docs, tests, SVG titles, README) for `Snipe-IT Onboarding` and `Snipe-IT Device Onboarding` and replace by **Handover Portal**:
- `FastAPI(title=...)` in `app/main.py` (and the test that asserts it, `tests/test_security_hardening.py`).
- Top bar title (`logo_lockup` default `title="Handover Portal"`); the subtitle is removed or replaced by a short neutral phrase chosen by you and listed in your report ("Device handovers").
- Page `<title>`: `{page} — Handover Portal` (some pages already use it; make all consistent, no duplicates like "Handover Portal — Handover Portal").
- Agent scripts print "Handover Portal Agent" (text change only in `agent.ps1` and `agent.sh`; no logic change; verify the scripts still run their syntax checks: `pwsh -NoProfile -Command "$null=[scriptblock]::Create((Get-Content static/agent.ps1 -Raw))"` if PowerShell is available and `bash -n static/agent.sh`).
- Do NOT rename the repository, Python packages, database names, environment variables, or the Snipe-IT product name where it means the real Snipe-IT system (for example "Snipe-IT connection", "push to Snipe-IT" stay).
- Add a single constant (`APP_NAME = "Handover Portal"`) in `app/config.py` and pass it to templates and the FastAPI title so the name lives in one place. Tests assert the name appears in the top bar and in the page title of every page, and that the string "Snipe-IT Onboarding" no longer appears in `app/`, `templates/`, `static/`, `tests/` (a grep-style test).

## 4.4 Verify visually
Rebuild the CSS (`npm run build:css`) if you added classes and commit `static/css/app.css`. Open `/`, `/handovers`, one case page, and the printable report in Chromium (Playwright) at 1440 px and 390 px, light and dark; look at the screenshots; check the logo is sharp, not stretched, readable in both themes, and aligned with the title. Say which screenshots you checked. If the browser cannot launch, `NOT RUN` with the error.

---

# PART 5: Final sync
Branch: `docs/hosted-portal-sync`, stacked on Part 4.
1. Update the LIVE GRAPH first (new modules: role domain, session repository/service changes, search filter function, anything else), then all affected principle files, `README.md`, `docs/security-review.md`, `docs/OPEN_QUESTIONS.md` (close Q-2, Q-3; update Q-4; add new questions), `docs/principles/09-decisions` (D entries for: roles, session store in database, code format and length, `PUBLIC_BASE_URL`, trusted proxies, recipient fields stored, branding), and the deployment guide (hosted mode, reverse proxy, roles configuration, PostgreSQL requirement for multi-worker).
2. If the repo has generated visual versions of the principles (`docs/principles/visual/`) run the build and its `--check`; commit the regenerated files.
3. Run: full test suite, `python -m compileall -q app tests`, `npm run build:css`, Alembic upgrade from empty and from the previous revision, downgrade one step and upgrade again.
4. `git status` clean except untracked prompt files.

## Open owner decisions (do NOT decide; list in your report)
1. The three Entra group object IDs (viewer, engineer, manager), and confirmation that the groups claim is enabled in the app registration ("Groups assigned to the application" recommended).
2. The post-logout redirect URL to register in Azure.
3. The b_labs logo file pushed into `static/img/` (and a dark-mode version if one exists).
4. Confirmation that employees' PCs can reach the portal address and port, and whether a reverse proxy sits in front (decides `TRUSTED_PROXIES` and whether `AGENT_IP_BINDING` can be `enforce`).
5. TLS is intentionally postponed; remind the owner in the final report that HTTP means session cookies and agent traffic are not encrypted.

## Forbidden
Weakening CSRF, CSP, rate limits or fail-closed checks; making any new route public; storing plain session codes; logging codes, tokens, emails or names; string-built SQL; `innerHTML` with data; inventing a logo; renaming real Snipe-IT references; new dependencies without asking; committing to `main`; claiming verification you did not run.

## Final report format
Per part: DONE / PARTIAL / BLOCKED. Per step: files changed, exact commands, exact results (pass/fail counts, concurrency test results on SQLite and on PostgreSQL, measured search time on 10,000 rows). List screenshots you actually opened. List everything `NOT RUN` with the exact error. List the proposed decisions and the open owner decisions above.
