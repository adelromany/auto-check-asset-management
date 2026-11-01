# HANDOFF — finishing visuals + real printing

Working branch: `feature/finish-visual-and-print` (from `origin/uncomplete2`).
Do **not** touch `main`, `uncomplete`, `uncomplete2`, `core_asset`, `printer_and_GPO`.
Read the task prompt sections 0–8 before continuing. Keep command output tailed; never
read `docs/visual/**/*.html` or `docs/visual/**/*.json`.

## Step list

1. Orient + baseline (this file, archify fetch, `build_visuals.py check`, full suite).
2. Merge `origin/core_asset`; drop the import-time `print()` banner in `app/config.py`;
   add printing modules/routes to the LIVE GRAPH; suite green except the known
   `test_static_page_matches_builder[graph-index]` (regenerated in Step 4).
3. Real printing inside the handover flow (domain, service, API, UI, docs, tests).
4. Regenerate visuals **once**, then the quality gate (visual-check + screenshots).
5. Final sync, full checks, delete this file.

## Log

(Append one line after every numbered step: `step N done: <hash> <what>; next: <N+1>; tests: <counts>`.)
