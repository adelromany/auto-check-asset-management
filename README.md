# Snipe-IT Device Onboarding (Handover Portal)

IT opens the portal, gets a short session code, runs an agent one-liner on
the employee's device; the agent POSTs its report back using that code.

## Project structure

```
main.py                 # compatibility entry point (uvicorn main:app still works)
app/
  main.py               # create_app(), router wiring, middleware; `app = create_app()`
  config.py             # the ONLY place env vars are read
  dependencies.py       # current_user, injectable session store
  auth.py               # Entra ID SSO: /login, /auth/callback, /logout
  schemas.py            # AgentPayload
  services/sessions.py  # SessionStore (create/get/submit/expire)
  routers/
    pages.py            # / and /api/me
    agent.py            # /api/session/new, /data, /submit
    snipeit.py          # /api/snipeit/device, /api/snipeit/health
    health.py           # /api/health
    diag.py             # /diag/clipboard (behind ENABLE_DIAG)
templates/              # index.html, diag_clipboard.html
static/
  app.js                # portal UI (uses shared copyText)
  js/clipboard.js       # shared copyText() utility (3 tiers, never silent)
  agent.ps1 / agent.sh  # device agent scripts served to targets
tests/
  conftest.py           # env-isolated app factory (see header comment)
  test_characterization.py  # pins current API behavior (must stay green)
  test_diag.py          # diagnostics page tests
  test_clipboard_playwright.py  # browser condition matrix (needs browsers)
docs/
  discovery.md          # code map produced before the refactor
  copy-diagnosis.md     # clipboard root cause, decision log, manual matrix
  https-deployment.md   # deferred TLS cutover checklist
```

## Run

```powershell
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080
# (equivalent: python -m uvicorn app.main:app --host 0.0.0.0 --port 8080)
```

Copy `.env.example` to `.env` and fill it in. SSO is ON unless
`SSO_ENABLED=false` (development only — startup prints a warning).

## Tests

```powershell
# fast API tests (no network, no browser)
python -m pytest tests/test_characterization.py tests/test_diag.py -q

# browser matrix (needs Playwright browsers once):
python -m playwright install chromium firefox webkit
python -m pytest tests/test_clipboard_playwright.py -q

# everything
python -m pytest tests/ -q
```

## Diagnostics

Set `ENABLE_DIAG=true`, restart, open `/diag/clipboard` on a failing and a
working device, and paste the report into the matrix in
`docs/copy-diagnosis.md`. See also `docs/https-deployment.md`.
