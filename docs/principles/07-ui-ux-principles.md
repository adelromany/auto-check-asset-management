# 07 — UI/UX Principles

The UI is server-rendered Jinja + vanilla JS, styled by Tailwind v4 with the shadcn token architecture already in `styles/app.css`. It must stay one consistent system.

## Consistency
- UIX-01 Reuse existing classes (`.card`, `.btn`, `.badge`, `.table`, `.tabs-*`, `.alert`, `.input`, `.separator`) and the design tokens. Do not introduce new colors, fonts, spacing scales, or one-off inline styles.
- UIX-02 Light, dark and system themes must work on every new page (use tokens, never hard-coded colors).
- UIX-03 Edit `styles/app.css`, never `static/css/app.css`. After template or style changes run `npm run build:css` and commit the generated file.
- UIX-04 No external fonts, scripts, icons or CDNs. The app must work on an offline LAN.
- UIX-05 Do not grow `static/app.js`. New behavior goes in new ES modules (`static/js/*.js`), each with one responsibility.

## Vocabulary
- UIX-06 Use Snipe-IT words on screen: Checkout / Checkin. One label per concept, everywhere. Serial numbers are labelled "Serial", always in a monospace style, always left-to-right.

## Hierarchy and flow
- UIX-07 Each screen has one primary action, visually distinct from secondary ones.
- UIX-08 The case page reads top to bottom as the real process: stages in order, the current/blocked stage visually prominent, the action for each stage next to it.
- UIX-09 Always show what is missing: a stalled or incomplete handover names the missing step and the reason in plain language, next to a button that fixes it (for example Retry).
- UIX-10 Forms are a single column. Group fields with whitespace rather than nested boxes.

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
