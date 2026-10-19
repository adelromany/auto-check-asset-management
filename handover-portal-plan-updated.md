# Plan: Modularize the Handover Portal + Fix "Copy" on Most Devices

**Repo:** `adelromany/auto-check-asset-management` (FastAPI, session-code agent flow)
**Base branch:** `feature/sso` (SSO work lives here, not on `sso`). Do not work directly on `feature/sso`. Create a separate branch for each independent task, based on `feature/sso` unless the task depends on another unmerged task branch. Use the branch naming conventions in Section 2.

---

## ملخص بالعربي (للمراجعة السريعة)

المطلوب مهمتين:

1. **التقسيم:** كل الكود الآن في `main.py`. نقسمه إلى modules و functions واضحة (routers رفيعة، services للمنطق، config واحد)، بدون أي تغيير في السلوك.
2. **مشكلة الـ copy:** الزر لا يعمل على معظم الأجهزة ويعمل على بعضها. الفرضية الأقوى: البورتال يُفتح عبر `http://IP:port` وهو **ليس Secure Context**، فيكون `navigator.clipboard` غير موجود أصلًا. **الـ HTTPS غير متاح حاليًا**، لذلك يجب أن يعمل الحل على `http://IP:port` كما هو: طبقة `execCommand` تصبح المسار الأساسي وليست احتياطيًا، ثم نافذة نسخ يدوي كضمان أخير، مع صفحة تشخيص تعمل على الأجهزة الفاشلة. الـ HTTPS مؤجل ومُوثّق فقط.
3. **الاختبار:** لا نختبر "على الأجهزة"، بل نعيد إنتاج **الظروف** التي تسبب الاختلاف (http مقابل https، API موجود أو محذوف، صلاحية ممنوحة أو مرفوضة) بـ Playwright، ثم جدول يدوي قصير على أجهزة حقيقية.

---

## 1. Goals and non-goals

**Goals**
- `main.py` only builds the app (create app, include routers, middleware). No business logic.
- Every function has one responsibility and can be tested without starting the server.
- Copy-to-clipboard works on every target device, or visibly falls back to a manual method. It must **never fail silently**.
- Must work over plain `http://IP:port` (or an internal http name). **HTTPS is not available currently**, so nothing in this plan may depend on it.
- A repeatable test strategy for behavior that depends on device/browser/URL.

**Non-goals (do not do these)**
- Do not change SSO behavior, URLs, response shapes, or the session-code agent flow.
- Do not add new product features.
- Do not commit `.env` or any secret. Do not print secrets in logs or tests.
- Do not configure real infrastructure (certificates, DNS). Only document it (see 6.4).

## 2. Ground rules for the agent

1. Work in small steps. **One commit per completed step**, with a message explaining the step. Run the relevant test suite after every step.
2. **Never mix a move with a behavior change.** Refactor commits move/reorganize code only; fix commits change behavior only.
3. If the code differs from what this plan assumes, adapt to the real code and note the difference in the final report. If the repo is small, fewer files are fine. Do not over-engineer.
4. Every independent task must use its own branch. Never commit directly to `feature/sso`, `main`, or another shared/base branch.
5. Unless a task depends on changes in another unmerged task branch, create its branch from the latest `feature/sso`. If it does depend on another task, state that dependency and use the required task branch as its base; do not silently mix unrelated work.
6. Use the branch naming and commit conventions below consistently.
7. Assumption to confirm in the final report: "copy" = the button that copies the check scripts to the clipboard in the handover flow. If other copy actions exist (for example copying a session code), they must use the same shared utility.
8. Ask the human only if blocked. Otherwise decide, document the decision, continue.

### Git branch naming conventions

Use lowercase names and forward slashes (`/`), never backslashes (`\\`):

- New feature: `feature/<short-kebab-case-name>` (example: `feature/clipboard-diagnostics`)
- Refactoring: `refactor/<short-kebab-case-name>` (example: `refactor/modularize-app`)
- Bug fix: `fix/<short-kebab-case-name>` (example: `fix/clipboard-copy`)
- Tests: `test/<short-kebab-case-name>` (example: `test/clipboard-playwright`)
- Documentation: `docs/<short-kebab-case-name>` (example: `docs/https-deployment`)
- Maintenance/tooling: `chore/<short-kebab-case-name>` (example: `chore/update-test-config`)

Do not put multiple independent tasks in one branch merely because they concern the same repository. Branch names describe the task, not the person or date.

### Git commit conventions

Use Conventional Commit-style prefixes, with a concise, specific message:

- `feat: <description>` — new feature
- `refactor: <description>` — code restructuring without behavior changes
- `fix: <description>` — bug fix
- `test: <description>` — tests
- `docs: <description>` — documentation
- `chore: <description>` — maintenance/tooling

Examples:
- `feat: add clipboard diagnostics page`
- `refactor: extract report generation service`
- `fix: support clipboard copy on insecure origins`
- `test: cover clipboard fallback behavior`
- `docs: document HTTPS deployment requirements`

### Pull request and branch hygiene

- Keep each branch focused on one independent task and open a Pull Request for review before merging into `feature/sso`.
- Do not merge a task branch until its relevant tests pass and the diff has been reviewed.
- If GitHub permissions or repository policy prevent opening a PR, report the limitation; do not bypass it by committing to the base branch.

## 3. Phase 0: Discovery (read-only, no code changes)

Produce `docs/discovery.md` containing:
- Every route in `main.py`: method, path, what it does, what it depends on.
- Every helper function, global variable, and piece of module-level state.
- Which templates and JS files exist, and where the copy logic lives (find every use of `clipboard`, `execCommand`, `copy`).
- How the portal is served today (run command, host, port, scheme) and how redirect URIs / cookies are built (relevant to HTTPS).
- A proposed mapping from current code to the target structure in Phase 2.

Stop and review the mapping against the real code before moving anything.

## 4. Phase 1: Safety net (before any refactor)

Add characterization tests with `pytest` + FastAPI `TestClient` that pin **current** behavior:
- Each route returns the same status code and response shape for representative inputs.
- The session-code agent flow: create a session code, use it, expired or invalid code behavior.
- Report and handover-sheet generation produce the same output for a fixed input (golden file).
- SSO routes: only test what can run offline (redirect construction, rejection when unauthenticated). Mock the Entra calls; never hit the real tenant.

Record the baseline: all tests pass on `feature/sso` before the first refactor commit.

## 5. Phase 2: Refactor into modules

Target structure (adapt names to the real code):

```
app/
  main.py              # create_app(), include routers, middleware. Nothing else.
  config.py            # all env/settings in one place (pydantic-settings)
  dependencies.py      # FastAPI Depends: current user, session validation
  auth/
    sso.py             # Entra login/callback logic
    session.py         # session/cookie handling
  routers/
    pages.py           # HTML pages
    agent.py           # session-code agent flow
    reports.py         # hardware/software report endpoints
    health.py
    diag.py            # clipboard diagnostics (Phase 3), behind ENABLE_DIAG
  services/
    session_codes.py   # create/validate/expire codes
    script_provider.py # returns the check scripts
    report_builder.py  # hardware/software report assembly
    handover_sheet.py  # fixed-template sheet generation
    mailer.py          # manager email with attachments
  schemas/             # pydantic request/response models
  templates/
  static/js/
    clipboard.js       # shared copyText() (Phase 3)
tests/
```

Rules:
- Routers are thin: parse input, call a service, return the response. No business logic in routers.
- Services take their dependencies as arguments (or via `Depends`), so they are testable without the server.
- No mutable module-level state. If state is needed (for example an in-memory session store), wrap it in a class and inject it.
- Settings are read only in `config.py`.
- Guideline: functions under about 40 lines; if longer, split by responsibility.
- Keep the run command working unchanged (`uvicorn app.main:app ...`, or whatever exists today).

**Acceptance for Phase 2**
- `main.py` is short (target under about 50 lines) and contains no route handlers.
- All Phase 1 tests pass, unchanged.
- App starts with the same command; SSO login still works locally.

## 6. Phase 3: Copy: diagnose, then fix

### 6.1 Hypotheses (ranked)

| # | Hypothesis | Why it explains "works on some devices only" |
|---|---|---|
| H1 | **Insecure context.** Portal opened via `http://IP:port` or an http internal name. `navigator.clipboard` exists only in secure contexts (HTTPS or localhost). | Works where it's opened via `localhost`/`127.0.0.1` or https, or where a browser flag/policy is set. Strongest candidate. |
| H2 | **User activation lost.** Code does `await fetch(...)` after the click and copies afterward; some browsers (notably Safari) reject the copy. | Browser-dependent. |
| H3 | **Permissions policy / iframe / enterprise browser policy** blocks `clipboard-write`. | Depends on the device's managed browser settings. |
| H4 | **Broken fallback.** `execCommand('copy')` fallback missing, or the hidden textarea uses `display:none` (cannot be selected), or iOS needs a different selection call. | Depends on browser. |
| H5 | **Copy succeeds but paste into PowerShell breaks** (multi-line paste, line endings, smart quotes, execution policy). Reported as "copy doesn't work". | Depends on the console and its settings. |

**Constraint:** HTTPS is not available, so H1 cannot be removed at the source. The fix must work on an insecure origin. In that condition `navigator.clipboard` is unavailable, so the `execCommand` path is the **primary** path, not an optional fallback. Getting H4 right (a robust `execCommand` implementation) is therefore the core of the fix.

### 6.2 Build the diagnostics first

Add a page `GET /diag/clipboard` (enabled by env flag `ENABLE_DIAG`, no secrets, read-only). It runs and displays:
- `window.isSecureContext`, `location.protocol`, `location.host`
- `typeof navigator.clipboard`, `typeof navigator.clipboard?.writeText`
- Permission state for `clipboard-write` (wrapped in try/catch; the Permissions API can throw)
- Result of **Method A** (`navigator.clipboard.writeText`) with error name and message on failure
- Result of **Method B** (`execCommand('copy')` via an off-screen textarea) including its boolean return value and `document.queryCommandSupported('copy')`
- A paste-target textarea so the engineer can verify what actually got copied
- `navigator.userAgent`, `navigator.platform`

Add two buttons: **Copy report** and **Download JSON**, so results can be collected from failing devices and pasted into the matrix (section 7.5). Optional: `POST /diag/clipboard/report` that logs the same fields server-side (no personal data).

Run this page on one failing and one working device **before** writing the fix, and record the findings in `docs/copy-diagnosis.md`. Do not assume H1; confirm it.

### 6.3 The fix: one shared utility

Create `static/js/clipboard.js` exporting `copyText(text)` that returns `{ ok: boolean, method: 'clipboard-api' | 'exec-command' | 'manual' }`:

1. If `window.isSecureContext && navigator.clipboard?.writeText` → try it.
2. On failure or if unavailable → `execCommand('copy')` fallback: create a `<textarea>` in the DOM (`position: fixed; opacity: 0`, **not** `display:none`), `focus()`, `select()`, `setSelectionRange(0, text.length)`, `execCommand('copy')`, then remove it and restore the previous focus/selection.
3. If both fail → open a small modal with a read-only textarea, preselected, and the text "Press Ctrl+C". Also offer a "Download .ps1" button.

UI requirements:
- Visible feedback every time: "Copied (N characters)" on success, a clear message on fallback. Never silent.
- Call `copyText` **synchronously** inside the click handler. If the script text must be fetched, pre-fetch it on page load or when the session code is created (H2). Optionally use `ClipboardItem` with a promise for Safari.
- Do not show a permanent "not HTTPS" banner (it is the known state and would be noise). Show a message only when **both** automatic methods fail and the manual-copy modal opens, including the likely reason (for example "the browser blocked automatic copy").
- Replace every existing copy implementation with this utility. No duplicated copy logic.

### 6.4 HTTPS is not available now (deferred) and an optional policy workaround

This plan does **not** depend on HTTPS. Do not add certificates or proxy configuration.

Document the following in `docs/copy-diagnosis.md` (short, no implementation):
- **Deferred root-cause fix:** when HTTPS becomes possible (a reverse proxy with a certificate from the company's internal CA on an internal DNS name), `navigator.clipboard` becomes available and tier 1 starts working with no code change. Keep the app proxy-friendly: honor `X-Forwarded-Proto` and make the cookie `Secure` flag configurable in `config.py`.
- **Optional workaround without HTTPS:** a managed-browser policy that treats the portal origin as secure (Chrome/Edge policy `OverrideSecurityRestrictionsOnInsecureOrigin`), pushed through Intune to the laptops. It only helps if the policy has reached the device before the IT engineer opens the portal on it, so it must be verified on a prepared laptop. Present it as an option for the human to decide; do not implement.
- **SSO caveat (out of scope here):** Entra ID generally rejects `http://` redirect URIs for non-localhost hosts, so SSO over `http://IP:port` will need separate attention. Mention it in the final report.

### 6.5 If tier 2 still fails on real devices (discuss, do not build without approval)

If the diagnostics show `execCommand` also fails on some target devices, write a short pros/cons note in `docs/copy-diagnosis.md` for approaches that avoid the clipboard:
- A downloadable `.ps1` bound to the session code (needs execution-policy handling; downloaded files may be flagged by SmartScreen).
- A short launcher one-liner typed by hand that fetches the script using the session code. Over plain http this has no transport protection or integrity guarantee, so it needs a security review before anyone considers it.

Do not implement either.

## 7. Phase 4: Testing a bug that depends on the device

**Principle:** do not try to test "on devices". Test the **conditions** that make devices differ, make each one reproducible, then confirm the remaining uncertainty on a few real devices.

Use `pytest-playwright` (Python, matches the repo). Do not add a second JS toolchain.

### 7.1 Reproduce the conditions in automated tests

Matrix: browser {chromium, firefox, webkit} × origin {secure: `http://localhost` or https, insecure: `http://<non-loopback LAN IP>`} × clipboard API {native, removed} × permission {granted, denied}.

The insecure-origin cells are the **production condition**, so they are the primary ones: every one must pass via tier 2 or tier 3. The secure-origin cells guard the future HTTPS case.

- **Insecure origin in CI:** start uvicorn on `0.0.0.0` and navigate to the machine's non-loopback IP. Chromium treats it as an insecure context, so `navigator.clipboard` is undefined. This reproduces H1 deterministically.
- **Remove the API:** `page.add_init_script("delete Navigator.prototype.clipboard")` (or define it as undefined) to force the fallback path.
- **Stub failures:** use init scripts to make `navigator.clipboard.writeText` reject with `NotAllowedError`, and `document.execCommand` return `false` or throw.

### 7.2 Verify the actual content

After clicking Copy, focus a test textarea and press `Control+V` (`Meta+V` on WebKit/macOS), then assert the textarea value equals the served script **exactly**. This works even on insecure origins because pasting into a page input does not need the Clipboard API. On secure origins in Chromium you may also grant `clipboard-read`/`clipboard-write` and read back directly.

### 7.3 Assertions

- Under the insecure origin: `window.isSecureContext === false` and `navigator.clipboard === undefined` (confirms reproduction).
- In every cell of the matrix: either the copy succeeds through some method, **or** the manual-copy modal appears. A silent failure fails the test.
- The success/failure feedback message is shown.
- No leftover textarea in the DOM after copying; focus is restored.
- Content integrity: SHA-256 of pasted text equals SHA-256 of the served script, including line endings. The UI shows the character count.

WebKit on Linux can have clipboard quirks in headless mode. Mark those cells best-effort (`xfail` with a documented reason), not skipped silently.

### 7.4 Unit-level cases for `copyText`

Method order is respected, return values are correct, and cleanup happens, for: API succeeds; API rejects; API missing; `execCommand` true; false; throws.

### 7.5 Manual device matrix (human, about 15 minutes)

Run `/diag/clipboard` on at least 2 failing and 2 working devices, **including the real target**: a freshly prepared Windows laptop (likely Edge) opened the way the IT engineer opens it during handover. Then test the full flow: click Copy, paste into PowerShell, run.

| Device | OS | Browser + version | URL used (http IP / hostname / https) | isSecureContext | Clipboard API present | Auto-copy result | Fallback result | Paste into PowerShell OK | Notes |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |

### 7.6 Exit criteria

- Automated suite green (with documented best-effort cells).
- Matrix (all rows using the real `http://IP:port` URL) shows every tested device succeeds via tier 2 or tier 3.
- No silent failure anywhere; if both automatic methods fail, the manual-copy modal appears with a reason.
- H5 checked: the pasted script runs in PowerShell on the target laptop.

## 8. Deliverables and final report

- Use focused branches and commits following Section 2. Recommended dependency/order: discovery docs → characterization tests → refactor steps → diagnostics feature → copy fix → copy tests → documentation. Create each task branch from the latest `feature/sso` unless it depends on an unmerged task branch; document any such dependency. Keep refactor-only commits separate from behavior-changing fix commits.
- Updated README: project structure, how to run tests, how to enable diagnostics, link to `docs/https-deployment.md`.
- Final report: what changed, what differed from this plan, test results, which cells are best-effort, what remains manual (the device matrix), and open questions for the human:
  1. Is "copy" only the script-copy button, or are there other copy actions?
  2. Which URL (http IP / hostname) is used on the failing devices?
  3. Which browsers are on the target devices?