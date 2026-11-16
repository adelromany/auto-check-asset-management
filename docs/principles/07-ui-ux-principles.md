# 07 — UI/UX Principles

The UI is server-rendered Jinja + vanilla JS, styled by Tailwind v4 with the shadcn token architecture already in `styles/app.css`. It must stay one consistent system.

## Consistency
- UIX-01 Reuse existing classes (`.card`, `.btn`, `.badge`, `.table`, `.tabs-*`, `.alert`, `.input`, `.separator`) and the design tokens. Do not introduce new colors, fonts, spacing scales, or one-off inline styles.
- UIX-02 Light, dark and system themes must work on every new page (use tokens, never hard-coded colors).
- UIX-03 Edit `styles/app.css`, never `static/css/app.css`. After template or style changes run `npm run build:css` and commit the generated file. The printable report has its own small self-hosted file, `static/css/report.css`, because it must not load the full app stylesheet.
- UIX-04 No external fonts, scripts, icons or CDNs. The app must work on an offline LAN. This is enforced by the self-only Content-Security-Policy in `app/security/headers.py`; do not add `unsafe-inline` or an external host.
- UIX-05 Do not grow `static/app.js`. New behavior goes in new ES modules (`static/js/*.js`), each with one responsibility. The legacy landing page only gained one "Start handover" link; the dashboard and case pages live in `static/js/handovers.js`, `static/js/handover_detail.js` and `static/js/shell.js`.
- UIX-19 The theme bootstrap is `static/js/theme-init.js`, loaded synchronously in `<head>`; it must stay external so the CSP can remain inline-free. The toggle itself remains `static/js/theme.js`.

## Vocabulary
- UIX-06 Use Snipe-IT words on screen: Checkout / Checkin. One label per concept, everywhere. Serial numbers are labelled "Serial", always in a monospace style, always left-to-right.

## Hierarchy and flow
- UIX-07 Each screen has one primary action, visually distinct from secondary ones.
- UIX-08 The case board lists operations in reading order. Operations are independent, so none is visually locked; a failed or not-done operation keeps its reason and next action visible.
- UIX-09 Always show what is missing: a stalled or incomplete handover names the missing step and the reason in plain language, next to a button that fixes it (for example Retry).
- UIX-10 Forms are a single column. Group fields with whitespace rather than nested boxes.
- UIX-20 `/dashboard` is the KPI overview; `/cases` shows the filters and one row per case; `/new` is the registration form; `/cases/{id}` is the case board with the operation checklist, recipient, Snipe-IT devices, signed sheet and event timeline; `/cases/{id}/history` is the full audit trail; `/device-check` is the agent device check.
- UIX-21 The printable report includes an explicit `[Company legal text goes here]` placeholder until the owner supplies approved wording; it must not invent legal claims.
- UIX-22 The case board stays calm: visible words are budgeted at 220 (1440 px), 160 (768 px) and 80 (390 px). Supporting panels and per-operation actions are disclosures; the board opens actions on desktop and keeps them collapsed on small screens. The audit trail is one click away rather than printed on the board.
- UIX-23 The accent is the `b_labs` teal and the neutrals are charcoal in both themes. Status colours (success, warning, destructive) stay semantic and always carry text, never colour alone.

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
