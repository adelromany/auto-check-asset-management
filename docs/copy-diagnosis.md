# Copy diagnosis: findings, decision log, and manual matrix

## 1. Confirmed root cause

**H1 (insecure context) CONFIRMED as the trigger; H4 (broken fallback) as the defect.**

- Automated proof (`tests/test_clipboard_playwright.py::test_insecure_origin_has_no_clipboard_api`,
  all 3 browsers): over `http://<LAN-IP>:8099`, `window.isSecureContext === false`
  and `typeof navigator.clipboard === "undefined"`. Over `http://127.0.0.1:8099`
  both exist. Same page, same browser — only the origin differs.
- The old handler (`static/app.js`, since replaced) called
  `navigator.clipboard.writeText` unconditionally with no fallback and no
  `.catch`, so on affected devices the click threw a TypeError and failed silently.
- H2 (lost user activation): mitigated by design — `copyText` is invoked
  synchronously in the click handler and the text is already in memory
  (pre-fetched at panel render), so no `await fetch` sits between click and copy.
- H3 (enterprise policy): cannot be ruled out per-device; tier 3 (manual modal)
  is the answer when policy blocks everything.
- H5 (paste breaks in PowerShell): not yet checked on a real target — see §4.

## 2. What was built (and why)

- `static/js/clipboard.js` — single shared `copyText(text, opts)`:
  tier 1 Clipboard API → tier 2 `execCommand` (now the **primary** path on
  `http://IP:port`, off-screen textarea, never `display:none`, focus restored)
  → tier 3 manual modal (preselected text + "Press Ctrl+C" + file download).
  Always resolves `{ok, method}` and always shows UI feedback. Never silent.
- Both copy buttons (Windows PowerShell / macOS-Linux tabs) use it; both show
  `Copied (N chars)` on success and `Copy manually` + modal otherwise.
- `/diag/clipboard` (behind `ENABLE_DIAG=true`): shows `isSecureContext`,
  protocol/host, clipboard API presence, `clipboard-write` permission state,
  runs Method A and Method B with error names, has a paste-target box, and
  offers Copy report / Download JSON / Send-to-server-log
  (`POST /diag/clipboard/report`, allow-listed fields only, no storage).
- Playwright suite reproduces H1 deterministically (serve on `0.0.0.0`, drive
  the LAN IP) plus API-removed / API-rejecting / execCommand-false stubs.
  23 passed, 2 skipped (by design), 2 xfailed (WebKit headless paste,
  best-effort, non-strict).

## 3. Deferred: HTTPS (root-cause fix for tier 1)

When a reverse proxy with a company-CA certificate on an internal DNS name
fronts the portal, `navigator.clipboard` becomes available and tier 1 works
with no code change. Requirements are documented in
`docs/https-deployment.md`. The app is already proxy-friendly: honors
`X-Forwarded-Proto` via uvicorn `--proxy-headers`, and the session-cookie
`Secure` flag follows `HTTPS_ONLY` in `app/config.py`.

**Optional workaround without HTTPS (human decision, not implemented):**
push a managed-browser policy treating the portal origin as secure
(Chrome/Edge `OverrideSecurityRestrictionsOnInsecureOrigin`) via Intune.
It only helps if the policy has reached the laptop *before* the engineer
opens the portal — verify on a prepared laptop first.

**SSO caveat:** Entra ID generally rejects `http://` redirect URIs for
non-localhost hosts, so SSO over `http://IP:port` needs separate attention
(current dev posture is `SSO_ENABLED=false` or localhost testing).

## 4. If tier 2 still fails on real devices (discuss first — NOT built)

- **Downloadable `.ps1` bound to the session code:** already partially eased —
  the tier-3 modal offers a file download. A standalone flow still needs
  execution-policy handling, and downloaded files may be flagged by SmartScreen.
- **Hand-typed launcher one-liner that fetches the script by session code:**
  over plain http there is no transport protection or integrity guarantee —
  requires a security review before anyone considers it.

## 5. Manual device matrix (human, ~15 minutes)

Run `/diag/clipboard` (needs `ENABLE_DIAG=true`) on at least 2 failing and
2 working devices **including the real target**: a freshly prepared Windows
laptop (likely Edge) opened exactly as during handover. Then: click Copy,
paste into PowerShell, run.

| Device | OS | Browser + version | URL used (http IP / hostname / https) | isSecureContext | Clipboard API present | Auto-copy result | Fallback result | Paste into PowerShell OK | Notes |
|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |
