@meta locale=en

# 07 — UI/UX Principles

The UI is server-rendered Jinja + vanilla JS, styled by Tailwind v4 with the shadcn token architecture already in `styles/app.css`. It must stay one consistent system.

## Consistency {#consistency-0}

| Rule | Text |
| --- | --- |
| UIX-01 {#uix-01} | Reuse existing classes (`.card`, `.btn`, `.badge`, `.table`, `.tabs-*`, `.alert`, `.input`, `.separator`) and the design tokens. Do not introduce new colors, fonts, spacing scales, or one-off inline styles. |
| UIX-02 {#uix-02} | Light, dark and system themes must work on every new page (use tokens, never hard-coded colors). |
| UIX-03 {#uix-03} | Edit `styles/app.css`, never `static/css/app.css`. After template or style changes run `npm run build:css` and commit the generated file. The printable report has its own small self-hosted file, `static/css/report.css`, because it must not load the full app stylesheet. |
| UIX-04 {#uix-04} | No external fonts, scripts, icons or CDNs. The app must work on an offline LAN. This is enforced by the self-only Content-Security-Policy in `app/security/headers.py`; do not add `unsafe-inline` or an external host. |
| UIX-05 {#uix-05} | Do not grow `static/app.js`. New behavior goes in new ES modules (`static/js/*.js`), each with one responsibility. The legacy landing page only gained one "Start handover" link; the dashboard and case pages live in `static/js/handovers.js`, `static/js/handover_detail.js` and `static/js/shell.js`. |
| UIX-19 {#uix-19} | The theme bootstrap is `static/js/theme-init.js`, loaded synchronously in `<head>`; it must stay external so the CSP can remain inline-free. The toggle itself remains `static/js/theme.js`. |

## Vocabulary {#vocabulary-1}

| Rule | Text |
| --- | --- |
| UIX-06 {#uix-06} | Use Snipe-IT words on screen: Checkout / Checkin. One label per concept, everywhere. Serial numbers are labelled "Serial", always in a monospace style, always left-to-right. |

## Hierarchy and flow {#hierarchy-and-flow-2}

| Rule | Text |
| --- | --- |
| UIX-07 {#uix-07} | Each screen has one primary action, visually distinct from secondary ones. |
| UIX-08 {#uix-08} | The case page reads top to bottom as the real process: stages in order, the current/blocked stage visually prominent, the action for each stage next to it. |
| UIX-09 {#uix-09} | Always show what is missing: a stalled or incomplete handover names the missing step and the reason in plain language, next to a button that fixes it (for example Retry). |
| UIX-10 {#uix-10} | Forms are a single column. Group fields with whitespace rather than nested boxes. |
| UIX-20 {#uix-20} | `/handovers` shows KPI tiles, filters (status, engineer, date range), and one row per handover with a status badge, serial, recipient, engineer, compact stage progress and a Missing column. `/handovers/{id}` is the case page with the stage checklist, software override, detected recipient identity, Snipe-IT devices, signed-sheet actions, preview and event timeline. |
| UIX-21 {#uix-21} | The printable report includes an explicit `[Company legal text goes here]` placeholder until the owner supplies approved wording; it must not invent legal claims. |

## States and feedback {#states-and-feedback-3}

| Rule | Text |
| --- | --- |
| UIX-11 {#uix-11} | Every list/table has three distinct states: loading (skeleton or spinner), empty (message with a next action), populated. |
| UIX-12 {#uix-12} | Every action gives feedback (toast or alert) in plain language that states what happened and the cause of failure; never a raw status code or stack trace. |
| UIX-13 {#uix-13} | Buttons that call the server show a loading state and are disabled while pending (no double submit). |
| UIX-14 {#uix-14} | Destructive actions (cancel handover, checkin) require a confirmation step that states the consequence. |
| UIX-15 {#uix-15} | Dates are shown in the user's locale; stored and transmitted in UTC. |

## Accessibility {#accessibility-4}

| Rule | Text |
| --- | --- |
| UIX-16 {#uix-16} | Every input has a real `<label>`. Every icon-only button has an accessible name. Every interactive element has a visible focus style. Body text meets WCAG AA contrast in both themes. |
| UIX-17 {#uix-17} | Status is never conveyed by color alone: badges carry text. |

## Safety {#safety-5}

| Rule | Text |
| --- | --- |
| UIX-18 {#uix-18} | Dynamic data is inserted with `textContent` or Jinja autoescape, never `innerHTML`. |

## Source {#source}

@facts
| Source Markdown | `docs/principles/07-ui-ux-principles.md` |
| SHA-256 | `6e7ed0da0b2464bf6259bfd7991917335f00c0296288bf2886c9333a70ca6390` |
| Repository link | [Open the Markdown source](https://github.com/adelromany/auto-check-asset-management/blob/main/docs/principles/07-ui-ux-principles.md) |
