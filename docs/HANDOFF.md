# HANDOFF — five-part owner review (A → E)

Base: `origin/docs/deployment-guide` @ `78fdb96`.
Branches, stacked: A `refactor/independent-operations` → B `feature/screens-split` →
C `feature/case-board-ui` → D `feature/maintenance-cases` → E `docs/ui-sync`.

## Baseline (step 1, inspected, no code changes)
- Suite: `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py`
  → **363 passed, 1 failed, 7 skipped** in 38.68 s. The one failure,
  `test_agent_flow_with_mismatched_serial_fails_stage_three`, passes in
  isolation (order-dependent shared state); recorded as a baseline flake.
- Visible word count (test client, tags stripped): `/handovers` = **105**,
  case page `/handovers/{id}` = **332**.
- Confirmed: `can_run` blocks on `STAGE_DEPENDENCIES` (409 "Waiting for …");
  any failed/blocked ⇒ case `stalled`; `record_agent_report` couples software
  and recipient; `/` is the agent page; `/handovers` is dashboard + creation
  form; no maintenance concept; one active case per serial via partial index.
- Brand: `static/img/b_labs.jpeg` = white `b_labs` wordmark on charcoal with a
  teal underscore. Accent = teal, neutral = charcoal.

step done: 1 inspection + HANDOFF created; next: A1/A2 domain rule + statuses; tests: 363 passed, 1 failed (order-dependent), 7 skipped
