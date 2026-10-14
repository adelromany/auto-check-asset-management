# EVALUATION REPORT — handover-portal-plan-updated execution

> Purpose: let ANOTHER model evaluate exactly what was done against
> `handover-portal-plan-updated.md` (untracked, repo root, 262 lines).
> How to verify anything below: `git log --all --oneline --graph`,
> `git diff <base>..<branch>`, then `git checkout <branch>` and run the
> commands in §6. Nothing was pushed; no PRs opened; nothing merged into
> `feature/sso`. The real `.env` (secrets) was never read, printed, edited,
> or committed — except two human-requested local-dev operations noted in §5.

## 1. Starting state (facts)

- Base `feature/sso` tip was `2d4a1eb` (merge of `check_programs` into SSO work).
  Working tree was CLEAN except untracked `handover-portal-plan-updated.md`.
  (Earlier sessions' SSO work had already been committed by the human:
  `68c62d4`, `675743f`, `f4623f9`, `2d4a1eb`.)
- Real code found (plan assumptions vs reality):
  - `main.py` was 347 lines (not just the SSO skeleton): it also had
    `/api/me`, `/api/snipeit/health`, `APP_HOST` default `localhost:8080`,
    and `AgentPayload.software_checks` + `windows_activation` (Phase-3 additions
    from the `check_programs` merge).
  - NO report generation / handover-sheet / email code exists anywhere, so
    plan §4's "golden file" requirement had nothing to pin (adapted, §4).
  - Exactly ONE copy action exists: per-tab `Copy` buttons in `static/app.js`
    (plan §2 question 7 answered: "copy" = script-copy buttons only; the
    session code is display-only, no copy button).
  - The copy bug was exactly H1+H4: `navigator.clipboard.writeText` only, no
    fallback, no `.catch` (`static/app.js` old lines 317–322).
- Environment: Python 3.14, no pytest/playwright libs; Playwright browser
  binaries for chromium-1217 already present. Installed during execution:
  `pytest 9.1.1`, `playwright 1.64.0`, `pytest-playwright 0.10.0`;
  downloaded firefox-1555, webkit-2370, chromium-1248 + headless shell.

## 2. Branch/commit map (all local, chained — deviation §4 explains why)

```
* (docs/evaluation-report, THIS file — tip commit below)  <- you are here
* c9a0583 docs: document clipboard diagnosis, HTTPS cutover and project layout
* 12e252e test: cover clipboard fallback behavior
* 5a504f2 fix: support clipboard copy on insecure origins
* a8dc3c0 feat: add clipboard diagnostics page
* 85fec91 refactor: move routes to routers behind create_app()
* da86f01 refactor: extract config, schemas and session store service
* a23ee88 test: add characterization tests pinning current behavior
| * b35a6e3 docs: add discovery notes mapping current code to target structure
|/       (branched from feature/sso, standalone)
* 2d4a1eb (feature/sso, untouched base)
```

| Branch (base) | Commit(s) | Files touched |
|---|---|---|
| `docs/discovery` (from `feature/sso`) | `b35a6e3` docs | `docs/discovery.md` (new) |
| `test/characterization` (from `feature/sso`) | `a23ee88` test | `tests/__init__.py`, `tests/conftest.py`, `tests/test_characterization.py` (new, 25 tests); `requirements.txt` (+pytest) |
| `refactor/modularize-app` (from `test/characterization` — needs its tests) | `da86f01` refactor, `85fec91` refactor | new `app/` package (below); root `main.py` → thin shim |
| `feature/clipboard-diagnostics` (from refactor tip) | `a8dc3c0` feat | `app/config.py` (+ENABLE_DIAG), `app/main.py` (+router), `app/routers/diag.py`, `templates/diag_clipboard.html`, `tests/test_diag.py` (4 tests) |
| `fix/clipboard-copy` (from diagnostics tip) | `5a504f2` fix | `static/js/clipboard.js` (new), `static/app.js` (copy handler only), `templates/index.html` (script tags only) |
| `test/clipboard-playwright` (from fix tip) | `12e252e` test | `tests/test_clipboard_playwright.py` (27 cells), `requirements.txt` (+pytest-playwright) |
| `docs/https-deployment` (from playwright tip) | `c9a0583` docs | `docs/copy-diagnosis.md`, `docs/https-deployment.md`, `README.md` (new), `.env.example` (+ENABLE_DIAG), `app/config.py` (+ENABLE_DIAG line — see deviation) |
| `docs/evaluation-report` (from docs tip) | this file | `EVALUATION_REPORT.md` (new) |

Final structure on this branch (lean adaptation of plan §5 — no reports/mailer
code existed to extract):

```
main.py                  # PEP-562 lazy shim -> app.main (uvicorn main:app unchanged)
app/__init__.py          # empty
app/main.py              # create_app() + app = create_app() + re-exports
app/config.py            # ONLY place os.getenv is read (+SSO WARNING, +ENABLE_DIAG)
app/dependencies.py      # get_store() (injectable), current_user()
app/auth.py              # oauth client + /login, /auth/callback, /logout
app/schemas.py           # AgentPayload (unchanged fields)
app/services/sessions.py # SessionStore class (identical TTL/code/submit semantics)
app/routers/pages.py     # / and /api/me   (/api/me folded here, not its own file)
app/routers/agent.py     # /api/session/new|{code}/data|{code}/submit
app/routers/snipeit.py   # /api/snipeit/device|health
app/routers/health.py    # /api/health
app/routers/diag.py      # /diag/clipboard + POST report (flag-gated)
```

## 3. Test results (actual, rerun commands in §6)

- Characterization: **25 passed** on `test/characterization`, and again
  **unchanged (same files, zero edits)** on `refactor/modularize-app`,
  diagnostics, fix, and playwright branches.
- Diagnostics: **4 passed** (`tests/test_diag.py`).
- Playwright (`tests/test_clipboard_playwright.py`, 9 tests × 3 browsers):
  **23 passed, 2 skipped** (copyText unit matrix intentionally chromium-only),
  **2 xfailed non-strict** (WebKit headless paste — the documented best-effort
  cells; they xfailed, i.e. the quirk is real).
- Full suite on `test/clipboard-playwright`: **52 passed, 2 skipped, 2 xfailed**.
- Key automated proofs: insecure origin (`http://<LAN-IP>`) has
  `isSecureContext === false` + `navigator.clipboard === undefined` on all 3
  browsers while `127.0.0.1` has both (H1 confirmed, not assumed); every copy
  cell ends in success-feedback or the manual modal (never silent); pasted
  bytes SHA-256 equal the served command; total-failure stub shows the modal
  with preselected exact text and Close works; no leftover textareas; focus
  restored; both `uvicorn main:app` and `uvicorn app.main:app` boot (200).
- `node --check` passes for `static/js/clipboard.js` and `static/app.js`.

## 4. Deviations from the plan (each deliberate — judge these)

1. **Chained branches instead of fully independent ones.** Rule §2.5 prefers
   independent branches from `feature/sso`, but §8 orders the work as a
   sequence (diagnostics → fix → tests) and each step's code/tests assume the
   prior step (diag router needs the refactor's `app/` layout; fix needs a
   home for `clipboard.js` wiring; playwright needs the fix). Independent
   branches off the monolith would have guaranteed merge conflicts in
   `main.py`. Documented here instead of silent.
2. **No `reports.py` / `handover_sheet.py` / `mailer.py` / `script_provider.py`.**
   That code does not exist in the repo (plan assumed it). The §4 "golden
   file" test was replaced with a full-payload submit→poll round-trip pinning
   `software_checks`/`windows_activation` passthrough.
3. **`/api/me` folded into `routers/pages.py`** instead of its own file —
   small repo, fewer files per rule §2.3.
4. **`REDIRECT_URI` is now import-time (`config.py`)** whereas old `main.py`
   read it per-request in `login`. Zero test impact; restart was already
   required for every other setting.
5. **Root `main.py` is a PEP-562 lazy shim**, not a static `from ... import`.
   Reason: the test helper reloads modules in `sys.modules` order (`main`
   first), so static `from app.main import app` would bind a stale app.
   Lazy `__getattr__` forwarding keeps `main.app / .current_user / .oauth`
   always current — this is what lets Phase-1 tests pass byte-identical.
6. **`app/config.py` gained its `ENABLE_DIAG` line inside the docs commit
   (`c9a0583`)**, not the diagnostics commit (oversight while wiring docs).
   One line, covered by `test_diag.py`; flag it, don't fail the run for it.
7. **`.env.example` is now TRACKED** (was untracked): committed in `c9a0583`
   with the human's local dev values (`SSO_ENABLED=false`, `DEV_*=Dev…`,
   empty AZURE_*/SESSION_SECRET — verified no real secrets). It also gained
   the `ENABLE_DIAG=false` template line.
8. **No pushes, no PRs, no merges into `feature/sso`.** All branches are local
   (prior standing rule forbade pushing). Human must push + open PRs in this
   order: `test/characterization` → `refactor/modularize-app` →
   `feature/clipboard-diagnostics` → `fix/clipboard-copy` →
   `test/clipboard-playwright` → `docs/https-deployment` → this branch
   (or squash per taste — but keep refactor/fix commits separate per rule §2.2).
9. **Manual device matrix (§7.5) NOT run** — no access to target devices from
   here. Table is ready in `docs/copy-diagnosis.md` §5. H5 (paste-into-
   PowerShell runs) is therefore unchecked on real hardware.
10. **Playwright `browser`/`browser_name` fixture names** were taken by
    pytest-playwright (collection error); tests use `target_browser` instead.
11. Diag-page "Copy report" uses a tiny inline clipboard+select fallback, not
    the shared `copyText` (which shipped one branch later) — intentional, to
    keep the diagnostics branch dependency-free.

## 5. Incidents and environment notes (for reproduction)

- `python -m pytest` needs repo root as CWD (relative `templates/`/`static/`,
  `load_dotenv()`); `tests/__init__.py` + `tests/conftest.py` (env-isolated
  factory, reload-based) handle the rest. The repo's real `.env` (with secrets)
  can never affect tests: conftest sets every var the app reads.
- `Secure`-flagged Keycloak cookies over plain http (seen in an earlier
  session, now irrelevant — Keycloak removed): real browsers accept them on
  `localhost`; Python cookie jars do not. Kept here only to explain old notes.
- Stale uvicorn processes holding port 8080 caused false readings twice;
  always `Get-NetTCPConnection -LocalPort <port>` before trusting a failure.
- `Secure` session cookies + `HTTPS_ONLY` default `true`: local http testing
  used `HTTPS_ONLY=false`; production checklist is in `docs/https-deployment.md`.

## 6. Rerun everything (copy-paste)

```powershell
cd D:\DevOps\B_labs\auto-check-asset-management
git checkout test/clipboard-playwright
pip install -r requirements.txt
python -m playwright install chromium firefox webkit   # once per machine
python -m pytest tests/test_characterization.py tests/test_diag.py -q   # fast, ~2s
python -m pytest tests/test_clipboard_playwright.py -q                  # ~2 min, needs browsers
python -m pytest tests/ -q                                              # full suite
node --check static/js/clipboard.js; node --check static/app.js
SSO_ENABLED=false python -m uvicorn main:app --port 8080  # manual smoke; /diag needs ENABLE_DIAG=true
```

Review diffs per phase:

```powershell
git diff feature/sso..test/characterization -- tests requirements.txt
git diff test/characterization..refactor/modularize-app -- app main.py
git diff refactor/modularize-app..feature/clipboard-diagnostics
git diff feature/clipboard-diagnostics..fix/clipboard-copy -- static templates
git diff fix/clipboard-copy..test/clipboard-playwright -- tests requirements.txt
```

## 7. Open questions (still for the human — plan §8)

1. Is "copy" only the script-copy button, or are there other copy actions?
   → Answered by code search: ONLY the two tab buttons (plus the new modal
   download). Confirm no hidden requirement.
2. Which URL (http IP / hostname) is used on the failing devices? → Needed to
   aim the manual matrix; the fix covers all insecure origins regardless.
3. Which browsers are on the target devices? → Likely Edge (Chromium) on fresh
   Windows laptops; confirm to prioritize the manual rows.
4. Merge strategy: sequential PRs (§4.8 order) or squash? And who pushes
   (needs repo write access)?
5. `.env.example` is now tracked with dev values — confirm that's acceptable,
   or blank `DEV_USER_*` before merging.
