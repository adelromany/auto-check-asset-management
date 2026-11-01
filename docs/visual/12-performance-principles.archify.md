@meta locale=en

# 12 — Performance Principles

Context: a small IT team (about 6 engineers), hundreds to low thousands of handovers per year, LAN deployment. Performance work is about correctness at this scale and avoiding traps, not about heroics.

## Targets {#targets-0}

| Rule | Text |
| --- | --- |
| PRF-01 {#prf-01} | Page and API responses that do not call Snipe-IT: p95 ≤ 300 ms with 10,000 handovers in the database. **Not measured**: no seed script or timing run was executed in this environment. |
| PRF-02 {#prf-02} | Dashboard summary: p95 ≤ 500 ms at 10,000 handovers (all aggregates in SQL). **Not measured**; the aggregates are SQL, but the timing target is unverified. |
| PRF-03 {#prf-03} | Calls to Snipe-IT: 10 s timeout; the UI shows progress and never freezes; a Snipe-IT slowdown never blocks pages that do not need it. |

## Rules {#rules-1}

| Rule | Text |
| --- | --- |
| PRF-04 {#prf-04} | Pagination is mandatory on every list endpoint (default 25, maximum 100). Never return unbounded lists. |
| PRF-05 {#prf-05} | Aggregates (counts, averages, group-bys) are computed by the database, never by loading rows into Python. |
| PRF-06 {#prf-06} | No N+1 queries: load related rows explicitly in one or two queries (`selectinload`/joins). The dashboard row query loads stages with `selectinload`; there is **no automated query-count test** yet (recorded in Q-7), so this is a code-review property, not a measured one. |
| PRF-07 {#prf-07} | Indexes exist for every filter used by list and dashboard queries: `handovers(status)`, `handovers(created_at)`, `handovers(engineer_email)`, `handovers(device_serial)`, `handover_stages(handover_id)`, `events(handover_id, at)`. The partial unique index on active handovers is both a rule and an index. |
| PRF-08 {#prf-08} | Do not call Snipe-IT inside loops when one call can answer (list a user's assets in one call). Idempotency checks read before they write. |
| PRF-09 {#prf-09} | Uploads are streamed with a size cap; the full file is never read into memory beyond the cap. |
| PRF-10 {#prf-10} | The event loop is never blocked: no blocking I/O or CPU-heavy work inside `async def`. File writes for uploads use async-safe patterns or small chunks. |
| PRF-11 {#prf-11} | Static assets: the generated CSS is minified (existing build); no new heavy assets; no polling faster than 2 s (the existing agent poll interval). |

## Verification {#verification-2}

| Rule | Text |
| --- | --- |
| PRF-12 {#prf-12} | The repeatable `scripts/seed_perf.py` and `docs/performance-notes.md` do **not** exist yet. The 10,000-handover timings were not measured, so no performance target is reported as met. This is Q-7 in `docs/OPEN_QUESTIONS.md`. |
| PRF-13 {#prf-13} | Stalled-by-age status is computed in SQL for summary counts and paged rows; no dashboard-wide Python scan is introduced. Query plans and 10,000-row timings remain unmeasured (Q-7). |

## Source {#source}

@facts
| Source Markdown | `docs/principles/12-performance-principles.md` |
| SHA-256 | `106453fea8da1f17abfe5b8247e7ab7308e278eb677420e25dc93c91c2205406` |
| Repository link | [Open the Markdown source](https://github.com/adelromany/auto-check-asset-management/blob/main/docs/principles/12-performance-principles.md) |
