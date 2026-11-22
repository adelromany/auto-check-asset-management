# D9 — Clipboard Playwright failures: cause and fix

Status: fixed. The failures were **test-targeting drift plus one real UI defect**.

## What failed

`tests/test_clipboard_playwright.py` opened the portal root (`/`) and waited for
`.copy-btn`, then read `.cmd-body.active .cmd-pre` and clicked
`.cmd-body.active .copy-btn`. After the UI recovery, `/` is the Dashboard and
the device check lives on `/sync`; the command blocks and copy buttons are only
rendered after "Start sync". The selector therefore never appeared and every
matrix cell failed with a 15 s selector timeout — not a clipboard regression.

## Real defect the tests also exposed (D2)

On `/sync` the copy buttons called `window.copyText(...)` without writing any
feedback into the button. On browsers where the Clipboard API and
`execCommand` both fail, the only feedback was the preselected manual modal; on
success the button label stayed "Copy", which reads as a dead control.

Fix: `copyWithFeedback(button, text)` in `static/js/sync.js` now

- shows "Copied N chars" for 2.5 s on success,
- shows "Copy manually" when `copyText` fell back to the manual modal,
- shows an error toast when copy is unavailable or throws,
- restores the original label afterwards (stored in `data-copy-label`).

The drawer's copy button uses the same helper.

## Test changes (no assertions weakened)

- `open_portal()` now opens `<origin>/sync` and starts a sync
  (`#sync-start-button` → `#sync-waiting` visible → `#sync-cmd-windows` text
  present).
- `first_command()` reads `#sync-cmd-windows`; `click_first_copy()` clicks
  `[data-copy-target="sync-cmd-windows"]`.
- The forced-failure test starts a sync instead of looking for a copy button on
  the Dashboard.
- The full matrix (3 browsers × secure/insecure origin, tier order, paste
  integrity, execCommand cleanup/focus, manual modal preselection, diagnostics
  page) is unchanged, including the documented WebKit xfails.
- One platform detail: Chromium on Windows normalises `\n` to `\r\n` when it
  writes to the system clipboard (verified by writing `"a\nb"` with
  `navigator.clipboard.writeText` and reading `"a\r\nb"` back). The secure-origin
  assertion therefore compares the pasted command with line endings normalised;
  the characters themselves must still match exactly. The command still runs
  unchanged in PowerShell.
