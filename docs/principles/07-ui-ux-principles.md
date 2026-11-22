# 07 — UI/UX Principles

The UI is server-rendered Jinja + vanilla JS, styled by Tailwind v4 with the shadcn token architecture already in `styles/app.css`. It must stay one consistent system.

## Consistency
- UIX-01 Reuse existing classes (`.card`, `.btn`, `.badge`, `.table`, `.tabs-*`, `.alert`, `.input`, `.separator`) and the design tokens. Do not introduce new colors, fonts, spacing scales, or one-off inline styles.
- UIX-02 Light, dark and system themes must work on every new page (use tokens, never hard-coded colors).
- UIX-03 Edit `styles/app.css`, never `static/css/app.css`. After template or style changes run `npm run build:css` and commit the generated file. The printable report has its own small self-hosted file, `static/css/report.css`, because it must not load the full app stylesheet.
- UIX-04 No external fonts, scripts, icons or CDNs. The app must work on an offline LAN. This is enforced by the self-only Content-Security-Policy in `app/security/headers.py`; do not add `unsafe-inline` or an external host.
- UIX-05 Keep UI scripts small and single-purpose under `static/js/`: `shell.js` (shell, drawers, toasts, omnibox, auto-refresh), `case.js`, `handovers.js`, `maintenance.js`, `sync.js`, `theme.js`, `theme-init.js`, `clipboard.js`, `diag_clipboard.js`. The retired `static/app.js` and `static/js/handover_detail.js` must not come back.
- UIX-19 The theme bootstrap is `static/js/theme-init.js`, loaded synchronously in `<head>`; it must stay external so the CSP can remain inline-free. The toggle itself remains `static/js/theme.js`.

## Vocabulary
- UIX-06 Use Snipe-IT words on screen: Checkout / Checkin. One label per concept, everywhere. Serial numbers are labelled "Serial", always in a monospace style, always left-to-right.

## Hierarchy and flow
- UIX-07 Each screen has one primary action, visually distinct from secondary ones.
- UIX-08 The case board lists operations in reading order. Operations are independent, so none is visually locked; a failed or not-done operation keeps its reason and next action visible.
- UIX-09 Always show what is missing: a stalled or incomplete handover names the missing step and the reason in plain language, next to a button that fixes it (for example Retry).
- UIX-10 Forms are a single column. Group fields with whitespace rather than nested boxes.
- UIX-20 The product has four destinations: `/` (Dashboard KPIs and attention), `/handovers` (kanban board, filters, registration drawer), `/maintenance` (needs / in / returned board, vendor panel, at-vendors table) and `/sync` (agent device check). Case pages are `/handovers/{id}` and `/maintenance/{id}`, each with `/history`. Older URLs (`/dashboard`, `/cases`, `/new`, `/device-check`) answer `308` and keep their query string.
- UIX-21 The printable report includes an explicit `[Company legal text goes here]` placeholder until the owner supplies approved wording; it must not invent legal claims.
- UIX-22 The case board stays calm via a 3-zone architecture: Sticky Passport (left), 3-lane Board (center), and Side-sheet Drawer (right). Visible words are strictly budgeted at 220 (1440 px), 160 (768 px), and 80 (390 px). Supporting evidence, secondary inputs, and per-operation forms live inside the drawer, keeping the board tranquil and readable at all viewports.
- UIX-23 The accent is the `b_labs` teal and the neutrals are charcoal in both themes. Status colours (success, warning, destructive) stay semantic and always carry text, never colour alone.
- UIX-24 Maintenance presents the three derived states (Needs maintenance, In maintenance, Returned) as lanes, a vendor panel with "here / avg / overdue", days-at-vendor clocks, and an at-vendors table (sent, expected return, reference). A vendor ("المورد") is a company that repairs devices.

## States and feedback
- UIX-11 Every list/table has three distinct states: loading (skeleton or spinner), empty (message with a next action), populated.
- UIX-12 Every action gives feedback (toast or alert) in plain language that states what happened and the cause of failure; never a raw status code or stack trace.
- UIX-13 Buttons that call the server show a loading state and are disabled while pending (no double submit).
- UIX-14 Destructive actions (cancel handover, checkin) require a confirmation step that states the consequence.
- UIX-15 Dates are shown in the user's locale; stored and transmitted in UTC.

## Accessibility
- UIX-16 Every input has a real `<label>`. Every icon-only button has an accessible name. Every interactive element has a visible focus style. Body text meets WCAG AA contrast in both themes.
- UIX-17 Status is never conveyed by color alone: badges carry text.

## Safety
- UIX-18 Dynamic data is inserted with `textContent` or Jinja autoescape, never `innerHTML`.

## Shell, keyboard and honesty
- UIX-25 Every screen uses `base.html`: the fixed 220 px rail with visible labels, the sticky top bar and the mobile bottom bar. Content is offset by the rail width so nothing sits underneath it.
- UIX-26 Keyboard: `/` focuses search, `n` opens the registration drawer, `Esc` closes drawers and the user menu, `Enter` submits. Hit targets are at least 40 px in both themes.
- UIX-27 No dead controls. Every button either acts and shows feedback (toast, label change, drawer, navigation) or is disabled with a visible reason. Lists auto-refresh every 15 s by replacing `[data-refresh-region]` and say "Updated just now"; an open drawer or a form being filled is never reset.
- UIX-28 The "All operations passed" chip appears only when every operation passed and there is at least one operation.
- UIX-29 Self-host the Inter and JetBrains Mono variable fonts and their OFL licenses under `static/fonts/`; do not fetch fonts from a CDN.
- UIX-30 Maintenance registration records reported issue, governed diagnosis category, priority and notes. Fresh and upgraded Alembic databases contain the default governed vendor/category lists; the UI must not depend on test-only seed hooks.
