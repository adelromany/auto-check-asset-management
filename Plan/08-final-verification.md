# Phase 08: Final verification (live, end to end) and handover to the owner

Prerequisite: `HANDOFF-V2.md` says `PHASE 07 DONE`. Nothing new is built here. This phase proves everything works with a REAL Snipe-IT and the real browser, and writes the evidence.

Rule: a scenario passes only with a printed result AND a check read back from Snipe-IT's API. If a scenario fails, fix the smallest thing, re-run that scenario only, and record it.

## Step 8.1 Fresh start
1. Reset the dev data: re-run `tools/snipeit_seed.py` (idempotent) and put every `TEST-SN-*` asset back to Ready to deploy with no user (small helper `tools/snipeit_reset_tests.py`, `TEST-` objects only; it refuses to touch anything else).
2. Use a fresh app database: `DATABASE_URL=sqlite+aiosqlite:///./data/verify_v2.db alembic upgrade head`.
3. Start the portal on port 8080 with the dev Snipe-IT in `.env`.
Check: `python tools/snipeit_probe.py` prints 11 PASS.

## Step 8.2 Live scenarios (script `tools/v2_verify_all.py`)
The script drives the HTTP API of the running portal (not internal functions) and reads Snipe-IT's API for proof. One function per scenario, each prints `PASS` or `FAIL <why>`:
- **S1 Full handover**: create case for `TEST-SN-0001`; device status Ready; simulate the agent report; software check passes; recipient `test.btech1`; no items; download the form (valid docx with the engineer name); checkout (Snipe-IT shows the user and Deployed); upload signed PNG (visible in Snipe-IT files); outcome `complete`.
- **S2 Company mismatch**: case for `TEST-SN-0003` (Mylo); choose `test.btech1`; expect `company_mismatch`; Snipe-IT unchanged.
- **S3 Recipient not in Snipe-IT**: case for `TEST-SN-0004`; mode `not_in_snipeit`; the other parts done; outcome `not_complete` and `missing` lists the recipient parts; later choose a real Nexta user `test.nexta1` and finish; outcome `complete`.
- **S4 No recipient**: case for `TEST-SN-0002`; device and software parts pass; mode `none`; outcome `ready`; the handover dashboard lists it under Ready labs for B.tech.
- **S5 Recipient items**: `test.btech2` has `TEST-SN-0005`; take it back in the case; Snipe-IT shows no assignee.
- **S6 Maintenance flow**: add `TEST-SN-0001` (after S1 it is assigned) with reason `Other` + text; set Maintenance; take back; add `TEST-SN-0002` with reason `Screen`; vendor `TEST-Vendor`; batch send both; dashboard `in_maintenance.total == 2`; batch receive one; Snipe-IT status Ready to deploy for it and Maintenance for the other; receive the second.
- **S7 Separation**: handover dashboard numbers do not change after S6; maintenance dashboard numbers do not change after S1 to S5 (compare the JSON before and after).
- **S8 Failure handling**: stop nothing; use a wrong token in a throw-away portal setting? No: instead call a case whose Snipe-IT asset id is invalid (set directly in the test database) and confirm the API returns a clear one-line error, not a 500.
Check: all PASS. Save the output to `docs/v2-verification.md` (date, commit id, one line per scenario, short Snipe-IT excerpts, no secrets).

## Step 8.3 Browser run
With the fake or the real Snipe-IT (prefer real when the stack is up), run the Playwright tests from phases 05 and 07, then one extra full journey in a single test: New handover, device status, recipient (mismatch disabled, then choose), print form (download event), upload, checkout, outcome Complete; then the Maintenance devices screen: add, set Maintenance, send batch, receive batch.
Also crawl every nav link: each returns 200 and none shows `{"detail":"Not Found"}`; every visible button is either clickable with a result or disabled with a visible reason (write a small crawler that clicks safe buttons; list any silent button as a defect).
Check: all green; crawler reports zero silent buttons and zero 404 links.

## Step 8.4 Quality gates
- `pytest -q` full suite green; list the final count.
- `ruff check .` and the formatter the repo uses.
- `pytest tests/test_architecture_rules.py -q` green (layering).
- Security: `git diff origin/fix/ui-recovery -- . ':!tests'` grep for the Snipe-IT token and any `verify=False`; CSRF and CSP tests still pass; no new inline script.
- Screenshots of the four screens in both themes saved to `docs/review/v2/` (desktop and 390 px).

## Step 8.5 Documents
- `docs/v2-verification.md` (from 8.2).
- `docs/OPEN_QUESTIONS.md` additions (one line each): the Nexta form template is missing; printing happens on the engineer's PC from the downloaded Word file; a "needs maintenance" device has a vendor only if a planned vendor is set; Snipe-IT status label names `Ready to deploy` and `Maintenance` are configurable; after maintenance the device does not return to the same user automatically.
- `HANDOFF-V2.md`: `PHASE 08 DONE`, final test count, the commit id, the list of known gaps.
- `README` section "V2": three lines on how to run the portal, the seed, and the verification script.
Commit and push the branch `feature/v2-handover-maintenance`. Do NOT merge. Do NOT open a pull request unless the owner asks.

## Step 8.6 Final message to the owner (plain, short)
State: branch name and commit id; the pass count of live scenarios (S1 to S8); the test count; screenshots path; the open items (forms for B.tech, Mylo, Nexta; label names; hosted printing); and the exact command to run the verification again. Nothing else.
