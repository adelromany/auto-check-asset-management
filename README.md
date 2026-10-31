# Snipe-IT Device Onboarding (Handover Portal)

IT opens the portal, gets a short session code, runs an agent one-liner on
the employee's device; the agent POSTs its report back using that code.

## Print Laptop Form

From the device details page, **Print Laptop Form** fills the
`templates/Laptop Form.docx` merge template with the device's latest
inventory (plus a best-effort Snipe-IT record lookup), converts it to PDF
with unattended LibreOffice, and submits it to the Windows Server print
queue configured in `PRINT_PRINTER`. Windows Server setup steps (printer,
tools, dedicated service account, permissions, logging, troubleshooting):
**docs/windows-printing.md**.

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
    printing.py         # Print Laptop Form: /api/print/*, /api/session/{code}/print
    health.py           # /api/health
    diag.py             # /diag/clipboard (behind ENABLE_DIAG)
templates/              # index.html, diag_clipboard.html
  Laptop Form.docx      # merge template ({{tokens}}) — starter committed,
                        # regenerate with scripts/make_laptop_form_template.py
static/
  app.js                # portal UI (uses shared copyText)
  js/clipboard.js       # shared copyText() utility (3 tiers, never silent)
  agent.ps1 / agent.sh  # device agent scripts served to targets
scripts/
  make_laptop_form_template.py  # generates the Laptop Form.docx starter
  print_smoke_test.py           # server-side pipeline sanity check (no print)
services (app/services):
  printing.py           # Windows print system: Get-Printer/Get-PrintJob/Ghostscript
  laptop_form.py        # {{token}} fill → PDF conversion → print submission
gpo/
  README.md             # GPO-based fleet collection (startup script + CSV share)
  agent-gpo.ps1         # headless twin of static/agent.ps1 (no session code)
  Launcher.bat          # GPO Startup wrapper (caches + runs agent-gpo.ps1)
  Deploy-AssetGPO.ps1   # one-shot AD setup: share + GPO + SysVol + link
  collect-anywhere.ps1  # collect from chosen machines right now (WinRM)
  Merge-DeviceData.ps1  # rollup: one row per device, Excel snapshot
tests/
  conftest.py           # env-isolated app factory (see header comment)
  test_characterization.py  # pins current API behavior (must stay green)
  test_diag.py          # diagnostics page tests
  test_print.py         # Print Laptop Form (mocked print system)
  test_clipboard_playwright.py  # browser condition matrix (needs browsers)
docs/
  discovery.md          # code map produced before the refactor
  copy-diagnosis.md     # clipboard root cause, decision log, manual matrix
  https-deployment.md   # deferred TLS cutover checklist
  windows-printing.md   # Print Laptop Form: server setup, service account, log
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
