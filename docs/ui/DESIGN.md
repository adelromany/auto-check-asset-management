# UI Architecture & Design System

## Four destinations, one shell

| URL | Screen | Purpose |
| --- | --- | --- |
| `/` | Dashboard | Open work, needs attention, stat tiles |
| `/handovers` | Handovers | Kanban board + filters + registration drawer |
| `/maintenance` | Maintenance | Three-state board, vendors, at-vendors table |
| `/sync` | Sync | Device check (agent command, result, attach) |

Case pages keep a child URL: `/handovers/{id}` (handover) or
`/maintenance/{id}` (repair), each with `/history`. Legacy URLs
(`/cases`, `/cases/{id}`, `/new`, `/dashboard`, `/device-check`) answer `308`
and preserve the query string.

Every page uses `base.html`: a fixed 220 px left rail with visible labels
(Dashboard, Handovers, Maintenance, Sync), a sticky top bar (omnibox, theme
toggle, user menu), and a mobile bottom bar with the same four destinations.
Content is offset by `md:pl-[220px]` so nothing slides under the fixed rail.

## Identity & tokens

Derived from `static/img/b_labs.jpeg`:

- **Ink**: `#1A1A1A` (`--brand-ink`, logo chip).
- **Mint accent**: `#71E3D9` (dark surfaces), deep mint `#0D766E` (light
  surfaces) — the underscore motif marks active nav and tabs.
- **Light surface**: warm off-white `#F6F7F5`; dark theme is first-class.
- **Logo**: `logo-chip-32/40/48` classes, `object-fit: contain`, never cropped;
  no inline styles (CSP `style-src 'self'`).

## Screen patterns

- **Dashboard**: five stat tiles (open handovers, stalled/with gaps, needs
  maintenance, at vendor, returned this week), an attention list, and two bar
  panels. `data-count` animates once.
- **Handovers**: a four-column kanban (`preparing`, `assigned`, `paperwork`,
  `done`) of compact cards with a 10-dot operation strip. Filters are radio
  chips remembered in `localStorage`; registration is a client-side drawer,
  never a server-rendered form.
- **Case page**: device passport (left) + three operation lanes (10 tiles).
  Every tile opens a side-sheet drawer whose controls act or are disabled with
  a visible reason. "All operations passed" appears only when every operation
  passed and there is at least one.
- **Maintenance**: needs / in / returned lanes, a collapsible vendor panel,
  days-at-vendor clocks, and an "At vendors" table with sent, expected return
  and reference.
- **Sync**: start → short code + copyable Windows/Unix commands → live result →
  attach to a case. Copy always gives visible feedback.

## Behaviour

- Keyboard: `/` focuses search, `n` opens the registration drawer, `Esc` closes
  drawers and the user menu, `Enter` submits.
- Lists refresh every 15 s by replacing `[data-refresh-region]`; the label says
  "Updated just now". Open drawers and forms are never reset.
- Buttons and links are never dead: each acts with feedback or is disabled with
  a visible reason. APIs answer JSON; browser navigations get a friendly HTML
  error page with the request id.
- No inline scripts/styles; external files only. `textContent` for all data.
