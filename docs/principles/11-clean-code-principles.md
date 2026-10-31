# 11 — Clean Code Principles

- CLN-01 Names reveal intent and use the project vocabulary (`handover`, `stage`, `checkout`, `checkin`, `recipient`, `engineer`). No abbreviations except well-known ones (`id`, `url`, `sha256`).
- CLN-02 Functions do one thing, ≤ 40 lines as a guide, ≤ 4 parameters (group extras into a dataclass or DTO). Files ≤ 400 lines; split by responsibility.
  **Known exceptions at final sync:** `app/services/snipeit_ops.py` (640 lines) and `static/js/handover_detail.js` (461 lines). Both are cohesive but too large; splitting them is recorded in Q-6 and is not claimed as done.
- CLN-03 Type hints on every function signature. Return types are explicit. No `Any` unless justified in a comment.
- CLN-04 Pure functions for rules; side effects only in services, repositories, clients.
- CLN-05 No duplicated logic: the second copy is extracted. The stage list, status values, and Snipe-IT paths exist in exactly one place.
- CLN-06 No magic values: stage keys and status values are enums/constants; limits come from `app/config.py`.
- CLN-07 Errors: raise specific exceptions (`SnipeItNotFound`, `StageNotRunnable`, …). Never catch broad `Exception` except at one boundary that logs and converts to a generic error. Never swallow errors silently.
- CLN-08 Comments explain WHY, not WHAT. Docstring on every module and public function (one or two lines). No commented-out code. No TODO without an entry in `docs/OPEN_QUESTIONS.md`.
- CLN-09 No dead code, no unused imports, no unused parameters.
- CLN-10 Keep the existing style: module docstring at top, f-strings, `async def` for I/O, formatting consistent with neighboring files. Do not reformat files you are not changing.
- CLN-11 Small public surface: helpers are private (`_name`). Routers contain no helper logic worth testing; if it is, it belongs in a service.
- CLN-12 Dates and times: timezone-aware UTC everywhere; `app/domain/timeutil.py` normalizes naive SQLite readbacks as UTC, and clocks are injected in domain/services for testability.
- CLN-13 JavaScript: ES modules, `const` by default, no globals except the small `window.HandoverShell` bridge, one responsibility per module, no `innerHTML` with data.
