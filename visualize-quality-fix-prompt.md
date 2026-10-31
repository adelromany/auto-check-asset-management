# Fix prompt: visual principle pages are poor + "Return to handover" button is broken + add the handover workflow visual

Repo: `auto-check-asset-management`. Three tasks (A visual quality, B broken button, C workflow visual). Work on branch `fix/visual-quality-and-return-button`. Tests first where behavior is testable. Commit after each part. Do not touch anything else. Report exact commands and exact results; do not claim you looked at a page unless you opened it in a browser and looked at the screenshot.

The owner's verdict on the visual principle pages (`docs/principles/visual/`): **colors are very bad, diagrams are tiny and unclear, and everything is squeezed inside small boxes/templates.** Treat this as a failed delivery: redo the visual design, do not patch it. Read the rules below completely before touching the generator.

---

## Part A. How to make a good visualization (rules, not suggestions)

### A0. First, look at what you made
1. Open `docs/principles/visual/index.html` and the GRAPH page in Chromium (Playwright, headless) at 1440x900 and at 390x844. Save screenshots to the scratchpad and LOOK at them. Write 5 concrete defects you actually see (for example "node text 9px", "gray on gray", "diagram occupies 30% of the width"). Fix those, then compare again. A change you did not look at does not count.

### A1. The diagram is the page, not a thumbnail inside a card
1. **Use the full width.** The GRAPH page layout for diagrams is full-bleed: the diagram container is at least `min(100%, 1400px)` wide, with no nested card around a card around an SVG. One section heading, then the diagram directly. No grey frame, no padding larger than 16px, no fixed small height.
2. **Size by content, not by a template.** Compute the SVG `viewBox` from the number of nodes and layers so nodes keep a readable size. Never shrink everything to fit a fixed box. If the graph is wider than the screen, let the container scroll horizontally and add zoom buttons (+, −, fit, 100%) and mouse-wheel plus ctrl zoom and drag-to-pan. Start at "fit to width" but never below a scale where text is under 14 CSS px; if fit would make text smaller than that, start at 100% and scroll.
3. **Minimum sizes (hard limits, test them):** node label font at least 14px at 100% zoom; node box at least 160x44; arrow stroke at least 1.5px; arrowheads at least 8px; gap between layers at least 90px; gap between nodes at least 24px. Add a test that parses the generated SVG and fails if any of these is violated.
4. **One diagram, one idea.** Do not put everything in one picture. Split the GRAPH visual into separate full-width sections, each with a title and a one-line "how to read this":
   - (1) Layers overview: only the layers as large bands with module counts and the allowed direction of dependency.
   - (2) Per-layer detail: modules of one layer at a time (tabs or a layer selector), each module as a clear box with its imports listed or drawn.
   - (3) Dependency focus: click a module to show ONLY its direct imports and importers (everything else dims to 15% opacity). Never draw all edges at full strength at once, because that is what makes it unreadable.
   - (4) Handover stage flow: nine (or ten) stage boxes left-to-right, large, numbered, with the dependency arrows and a legend.
   - (5) Violations and freshness: a short list and badge; "0 violations" must be visible when true.
5. **Edges:** route arrows in straight or orthogonal lines between layer bands. Avoid crossing through nodes. When many edges would overlap, bundle them or show them only on hover/click of a node. Show the edge count on hover.
6. **Labels:** show the short module name (`software_check`), and the full path on hover and in a side details panel. Never truncate with an ellipsis without a tooltip. Never rotate text.

### A2. Color: a small, deliberate, accessible palette
Delete the current palette. Use this method:
1. **Neutrals:** page background `#FFFFFF` (dark: `#0F1419`), surface `#F6F8FA` (dark: `#161B22`), border `#D0D7DE` (dark: `#30363D`), text `#1F2328` (dark: `#E6EDF3`), muted text `#57606A` (dark: `#9AA4AF`). Body text must be at least 7:1 against its background (AAA), muted text at least 4.5:1.
2. **Layers (5 colors, one per layer, same in light and dark, never reused for anything else):**
   - routers `#0969DA` blue
   - services `#1A7F37` green
   - repositories/clients `#9A6700` amber
   - db/external `#8250DF` purple
   - domain `#CF222E` is NOT allowed here (red is reserved for errors). Use teal `#0A7C86` for domain.
3. **Meaning colors (used only for status, always with an icon and a text label, never color alone):** ok `#1A7F37` with a check; warning `#9A6700` with a triangle; violation/error `#CF222E` with a cross. Do not use these three for layers.
4. **Fills are tints, outlines are the full color:** node fill = the layer color at 12% (light) or 22% (dark) over the surface; node border = full layer color 2px; node text = main text color (not the layer color) so it is always readable.
5. No gradients, no shadows heavier than 1px, no neon, no more than these colors on a page. Check every text/background pair with a contrast function in the generator and make the build FAIL if a pair is under its required ratio (4.5:1 normal text, 3:1 large text and graphical objects). Print the table of checked pairs in the build output.
6. Dark mode is designed, not inverted: use the dark values above and re-run the contrast check for both themes.
7. Color-blind safety: besides color, every layer also gets a distinct shape marker or a pattern in its band header (for example different corner icon) and its name written in the band.

### A3. Typography and spacing
1. Base text 17px, line height 1.65, max line length 75ch for prose. Headings clearly stepped (32/24/20/18). System font stack. Monospace 15px for code and module names.
2. Section spacing at least 48px between major sections, 16px inside. Do not nest bordered boxes more than one level deep.
3. The page content width: prose column 75ch; diagram sections full width up to 1400px; the sticky TOC must not shrink the diagram (put the TOC in a collapsible left rail that can be hidden with one click, remembered in localStorage inside try/catch).

### A4. Interaction that actually helps
Search, tabs for layers, click-to-focus on a module, keyboard navigation (Tab moves between nodes, Enter focuses, Esc clears), a details panel (name, layer, file path, imports, imported by, line count) that opens on the side on wide screens and below the diagram on narrow screens, and a legend that stays visible (sticky) while scrolling the diagram. Print: hide controls and print each diagram on its own page in landscape.

### A5. Verify for real
1. Rebuild with `python tools/build_principles_visual.py` (or the repo's command) and run its `--check`.
2. Screenshots at 1440x900 and 390x844, light and dark, for: index page, one prose principle page, and each of the five GRAPH sections. Open them and judge: Is every label readable without zooming? Does the diagram fill the width? Are there boxes inside boxes? Is anything cut off? Fix and repeat until the answer is clean. List which screenshots you checked.
3. Automated checks: the SVG size test (A1.3), the contrast test (A2.5), no external network requests, no console errors, tab order works.
4. Ask the owner to review the first rebuild before you do anything else on this part if any of these fail: you cannot launch a browser, or you cannot get node text to 14px at fit-to-width. Say so plainly.

---

## Part B. Button "Return to handover" is visually broken

What the owner sees (screenshot of `/?handover_id=…`, the "Device check for this handover" card): the label text "Return to handover" is drawn OUTSIDE the card, to the left of the page content (its left edge is left of the card's left border), and a small empty rounded box (the button's border/circle) sits below the paragraph, offset and not around the text. So the border/background belongs to an empty element, and the text escapes it.

Likely causes (check each in the code; do not assume):
1. The button/link is an element with a fixed small width/height, or `display: inline-flex` with `overflow: visible`, and its label is in a child that is positioned or has negative margin, so the text is not inside the bordered box.
2. A Tailwind/shadcn class on the wrapper is missing from the built CSS (`static/css/app.css` is generated: a class used in the HTML/JS but not present in the build gives exactly this "empty box, loose text" effect). Run `npm run build:css` and check the class exists.
3. The element is created in JS (`static/js/*.js`) with classes that differ from the shared button classes used elsewhere, or the icon span has `size-*` classes while the label span is outside the `<a>`/`<button>`.
4. A global `a` or `.btn` rule with `margin-left` or `transform`.

Do this:
1. Find the markup: search all of `templates/`, `static/js/`, `static/css/` and `app/` for the text "Return to handover" and the card title "Device check for this handover". Show the file and lines you found.
2. Reproduce first: write a Playwright test (or add to the existing browser tests) that opens that page with a seeded handover, finds the link by its text, and asserts: the link's bounding box CONTAINS the text's bounding box, the link is inside the card's bounding box, the link has non-zero width and height, the border radius is consistent, and the focus ring surrounds the whole link. The test must fail before the fix. If Playwright cannot run, say `NOT RUN` and write the check as a plain DOM/class test of the markup instead.
3. Fix it by using the SAME button component classes used by the other buttons on the site (for example the "Copy" button in the same screenshot): the label and the icon inside ONE element, `inline-flex items-center gap-2 px-3 py-2 rounded-md border`, no fixed width, no negative margin, `whitespace-nowrap`. Place it in the card's action area with normal spacing (a margin-top of 16px under the paragraph, aligned with the paragraph's left edge).
4. Rebuild the CSS (`npm run build:css`), commit the rebuilt `static/css/app.css`, and check the same component in dark mode and at 390px width.
5. Search the whole UI for other links or buttons built the same wrong way (same classes or same JS helper). List them; fix any that show the same symptom.
6. Take before/after screenshots of that card (1440 wide and 390 wide, light and dark) and compare them. Say which ones you checked.

---

## Part C. Visualize the device handover workflow (new page)

Create ONE more generated page: `docs/principles/visual/handover-workflow.html`, linked from the index with its own prominent card ("Device handover workflow"). Same rules as Part A (full width, readable sizes, palette, contrast checks, no external resources, deterministic output, covered by `--check`). This page is for the IT engineers and the owner, so it must be understandable by someone who has never read the code.

### C1. Single source of truth (no invented flow)
1. Read the stage list, order, dependencies, and rules from the code, not from memory: `app/domain/stages.py` and `app/domain/handover_rules.py` (and `app/domain/software_rules.py` if present). Import the pure modules or parse them in the generator. Include every stage that exists in the code (for example `device_prepared`, `user_signed_in`, `agent_report`, `software_check`, `recipient_check`, `checkout`, `report_printed`, `user_signed`, `document_scanned`, `document_pushed`). If the code has more or fewer, the page follows the code.
2. Read the owner's briefing/diagram description if it exists in the repo (search `docs/` for the handover briefing) and compare. Show any mismatch between the briefing and the code in a "Differences" box at the bottom; never hide it and never silently fix the diagram to match the document.
3. Statuses come from the code too (for example pending, passed, failed, skipped, blocked, overridden). Use exactly those names.

### C2. What the page must show (each as its own full-width section)
1. **The main flow:** all stages as large numbered boxes left to right (wrap to a second row on narrow screens, never shrink below the Part A minimum sizes). Each box shows: number, human title, WHO acts (engineer, employee, agent, Snipe-IT, system), and a one-line "done when". Arrows show dependencies. Stages that can be skipped or overridden have a visible badge with its rule (for example "software: override with reason, never hardware").
2. **Swim lanes:** the same flow redrawn with lanes for Engineer, Employee (device user), Local agent, Portal, Snipe-IT. Each step sits in the lane of who does it; arrows cross lanes. Show which steps write to Snipe-IT (checkout, file upload) with a distinct marker, and which are read-only. Mark the one irreversible-looking step clearly.
3. **Stage detail panel:** click a stage to see: what the engineer does, what the system checks, what blocks it (the exact rule text from the code docstring or rule table), what the dashboard shows when it is missing ("what each case lacks"), and the related rule IDs from the principle files (clickable).
4. **Failure and recovery paths:** for each stage, the typical failure (agent report missing, software missing, recipient not found in Snipe-IT, checkout verification mismatch, wrong file type on upload, push not verified) and what the engineer does next. Draw them as dashed side branches coming off the stage, red outline plus an icon and text (never color alone).
5. **Case lifecycle:** a small state diagram of the whole case (for example open, in progress, stalled, completed, cancelled) with the rule for each transition, read from the code (including the stalled-by-age rule if implemented).
6. **Example walkthrough:** one concrete fictional case (device `TEST-SN-0001`, user `TEST-recipient`) shown as a timeline with what happened at each stage and the evidence that exists after it (agent report, event row, Snipe-IT call, PDF hash). Mark it clearly as an example. Do not use real names, serials, or tokens.
7. **Legend and "how to read this"** at the top, sticky while scrolling.

### C3. Interaction
Hover/focus highlights a stage and its direct prerequisites and dependents (the rest dims); a toggle switches between "main flow" and "swim lanes"; a toggle "show failure paths"; print layout prints each section on its own landscape page; fully keyboard operable; works in light and dark.

### C4. Tests and verification
1. A test builds the page and asserts: the stage names and order in the HTML equal the code's stage list exactly; every dependency edge in the page equals the code's dependencies; every stage has a "who acts" value and a "done when" text; no stage appears twice.
2. A test that fails if a stage is added to the code but the generated page was not regenerated (covered by `--check`).
3. Screenshots at 1440x900 and 390x844, light and dark, of each section; open them and judge as in A5. List which ones you checked.
4. Add the new generator module and any new tool file to the LIVE GRAPH so `tests/test_graph_consistency.py` stays green. Add the new page to the principles index and to the docs list in `README.md`.

---

## Final report
Part A, Part B and Part C: DONE / PARTIAL / BLOCKED, files changed, exact commands with exact results (test counts, `--check` result, contrast table summary), the list of screenshots you looked at and what you changed because of them. Do not report anything as verified that you did not open and look at.
