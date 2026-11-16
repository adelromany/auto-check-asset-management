# UI Architecture & Design System

## Identity & Tokens
Derived directly from `static/img/b_labs.jpeg`:
- **Dark Surface / Ink**: `#1A1A1A` (`oklch(0.20 0.005 180)`).
- **Brand Accent / Mint**: `#71E3D9` (`oklch(0.84 0.13 183)`) for dark surfaces; deep mint `#0D766E` (`oklch(0.48 0.10 183)`) for light surfaces to guarantee 4.5:1 text contrast.
- **Light Surface**: Warm off-white `#F8F9FA`.
- **Brand Motif**: The mint underscore `_` from `b_labs` underlines active nav links, active tabs, and omnibox focus state.
- **Logo**: 32px rounded chip with `b_labs.jpeg`, accompanied by "Handover Portal".

## Shell Structure
- **Left Rail (Desktop)**: Slim icon+label navigation bar (`w-16` expandable to `w-52`):
  1. Dashboard (`/`)
  2. New Case (`/new`)
  3. Cases (`/cases`)
  4. Maintenance (`/cases?kind=maintenance`)
  5. Device Check (`/device-check`)
- **Bottom Navigation (Mobile < 768px)**: Fixed 5-tab bar.
- **Top Bar**: Search Omnibox with command-palette overlay (`/` hotkey), theme toggle, and current user avatar.
- **Zero Nav Duplication**: No page repeats header navigation or duplicate breadcrumb cards.

## Signature Interactions
1. **Operation Strip**: Cases render an inline dot matrix (`stage-dots`) representing the 10 handover stages or 4 maintenance stages, color-coded with state tooltips.
2. **Command Palette**: Omnibox triggers instant search across Cases, Devices, People, and Vendors.
3. **Calm Density**: Zero paragraphs on operation tiles. Each card represents exactly one concept with concise stats and badges.

## Case Board (`/cases/{id}`)
Three-zone responsive grid:
1. **Device Passport (Left, Sticky `w-72`)**: Device serial in monospace, model chip, asset tag, recipient avatar + name, engineer, ticket, SVG progress ring (`n/m done`), gaps counter, primary **Next action** button, and secondary action menu (`⋯`).
2. **Operations Board (Center)**: Grouped into three visual lanes:
   - **Prepare**: Device prepared, User signed in, Agent report, Software.
   - **Assign**: Recipient, Checkout.
   - **Paperwork**: Print form, Signed paper, Scan, Push.
   Each tile contains: icon, ≤3-word title, status badge, ≤60-character result summary, primary verb, and `⋯` secondary menu.
3. **Operation Drawer (Right Side Sheet)**: Slide-over drawer focused exclusively on the active operation's interactive controls, with standard footer ("Mark not done", "Retry").

## History & Maintenance
- **History (`/cases/{id}/history`)**: Chronological day-grouped timeline with human sentences, 2s actor event coalescing, and hidden collapsible raw JSON.
- **Maintenance Lanes**: Kanban board organized by `Needs maintenance`, `In maintenance`, and `Returned from maintenance`.
