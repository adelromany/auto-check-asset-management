# 01 — Test Principles

Scope: every change in this repository. IDs (TST-xx) are cited in reviews and reports.

## Strategy
- TST-01 Pyramid: many fast unit tests (domain, services), fewer integration tests (API + DB), very few browser tests (Playwright).
- TST-02 Characterization tests (`tests/test_characterization.py`, `tests/test_diag.py`) pin existing behavior. They are read-only: never edited to make a change pass. If one fails, the change is wrong.
- TST-03 Pure logic (`app/domain/*`) is developed test-first with table-driven cases. Coverage target 100%.
- TST-04 Services and repositories: coverage target ≥ 85% lines. Whole `app/` target ≥ 75%.
- TST-05 Every bug fix starts with a failing test that reproduces it.

## Test types and tooling
- TST-06 Async code is tested with `pytest-asyncio` (`asyncio_mode = auto`). API tests use `httpx.AsyncClient` with `ASGITransport` so the test and the app share one event loop.
- TST-07 Database tests use SQLite in memory (aiosqlite). When `TEST_DATABASE_URL` points to PostgreSQL, the migration and constraint tests also run there. A skipped PostgreSQL run is reported as "not exercised", never as passed.
- TST-08 External systems are never called for real: Snipe-IT is replaced by the stateful fake in `tests/fakes/snipeit_fake.py` (built on `httpx.MockTransport`). Live tests are marked `live`, opt-in via `SNIPEIT_LIVE_TEST=1`, and may only touch records whose names start with `TEST-`.
- TST-09 Tests must be deterministic: no sleeps for timing, no dependence on test order, no dependence on a developer's `.env`. Freeze or inject time where it matters.
- TST-10 Each test creates its own data and leaves no state behind.

## What must always be tested
- TST-11 Authorization: every new route has a test for 401 (not logged in).
- TST-12 Validation: invalid input returns 4xx with a clear message, never 500.
- TST-13 Idempotency: repeating a Snipe-IT write step performs at most one external write.
- TST-14 Failure paths: network error, Snipe-IT 401/404/5xx, verification mismatch.
- TST-15 Security regressions: path traversal on uploads, script injection in text fields, token never present in logs.
- TST-16 Architecture rules (`tests/test_architecture_rules.py`) and graph consistency (`tests/test_graph_consistency.py`) run in the normal suite.

## Acceptance criteria for a change
- All original 29 tests pass. New tests pass. `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py` is green.
- Playwright tests are run when the UI or clipboard code changed and browsers are installed; otherwise reported as "not run".
