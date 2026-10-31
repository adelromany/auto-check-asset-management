# 01 — Test Principles

Scope: every change in this repository. IDs (TST-xx) are cited in reviews and reports.

## Strategy
- TST-01 Pyramid: many fast unit tests (domain, services), fewer integration tests (API + DB), very few browser tests (Playwright).
- TST-02 Characterization tests (`tests/test_characterization.py`, `tests/test_diag.py`) pin existing behavior. They are read-only: never edited to make a change pass. If one fails, the change is wrong. The 29 tests in these two files are the compatibility contract and are still green.
- TST-03 Pure logic (`app/domain/*`) is developed test-first with table-driven cases. Coverage target 100%.
- TST-04 Services and repositories: coverage target ≥ 85% lines. Whole `app/` target ≥ 75%. **Not measured in this environment**: `pytest-cov` could not be downloaded, so no coverage percentage is claimed. The target stays as the review standard once the tool is installed.
- TST-05 Every bug fix starts with a failing test that reproduces it.

## Test types and tooling
- TST-06 Async code is tested with `pytest-asyncio` (`asyncio_mode = auto`). API tests use `httpx.AsyncClient` with `ASGITransport` so the test and the app share one event loop.
- TST-07 Database tests use SQLite in memory (aiosqlite). When `TEST_DATABASE_URL` points to PostgreSQL, the migration and constraint tests also run there. **Not exercised in this environment**: `asyncpg` could not be installed, so the PostgreSQL run is reported as skipped, never as passed.
- TST-08 External systems are never called for real: Snipe-IT is replaced by the stateful fake in `tests/fakes/snipeit_fake.py` (built on `httpx.MockTransport`). Live tests are marked `live`, opt-in via `SNIPEIT_LIVE_TEST=1`, and may only touch records whose names start with `TEST-`. Live verification is BLOCKED here (Docker Hub timeouts); see `docs/snipeit-api-verified.md`.
- TST-09 Tests must be deterministic: no sleeps for timing, no dependence on test order, no dependence on a developer's `.env`. Freeze or inject time where it matters.
- TST-10 Each test creates its own data and leaves no state behind.

## What must always be tested
- TST-11 Authorization: every new route has a test for 401 (not logged in).
- TST-12 Validation: invalid input returns 4xx with a clear message, never 500.
- TST-13 Idempotency: repeating a Snipe-IT write step performs at most one external write.
- TST-14 Failure paths: network error, Snipe-IT 401/404/5xx, verification mismatch.
- TST-15 Security regressions: path traversal on uploads, script injection in text fields, token never present in logs.
- TST-16 Architecture rules (`tests/test_architecture_rules.py`) and graph consistency (`tests/test_graph_consistency.py`) run in the normal suite.
- TST-17 Security regressions run in `tests/test_security_hardening.py`: fail-closed startup, CSRF token/Origin, self-only headers, rate limiting and the tracked-file secrets scan.
- TST-18 Dashboard aggregates and pages run in `tests/test_dashboard.py`; documents in `tests/test_documents.py`; Snipe-IT writes in `tests/test_snipeit_write_ops.py`.

## Acceptance criteria for a change
- All original 29 tests pass. New tests pass. `python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py` is green.
- Playwright tests are run when the UI or clipboard code changed and browsers are installed; otherwise reported as "not run".
