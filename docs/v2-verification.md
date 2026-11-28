# V2 Final Verification

## Polish (2026-11-28)

Branch: `feature/v2-polish`. Verified working tree based on `fe65711`; the PART 4-9 commits are awaiting the owner's required git confirmation, so no polish commit id or push is claimed here.

### Automated evidence

- Full non-e2e suite: **656 passed, 13 skipped, 2 xfailed** (`pytest -q --ignore=tests/e2e`), including migration up/down/up coverage and 13 standalone Playwright scenarios.
- Standalone browser coverage verifies maintenance action success/error states and reload persistence, Apply visibility, successful PDF printing without a download, maintenance Devices open-handover cancellation, device milestone cards, dashboard/mobile word budgets, and a 12-page navigation crawl.
- Full suite including repository e2e fixtures: **645 passed, 13 skipped, 2 xfailed, 2 failures subsequently fixed, 3 setup errors**. The errors are all Snipe-IT HTTP 503 during fixture setup. The final non-e2e rerun above is green.
- Architecture and graph consistency: **100 passed**. Principle visuals regenerated and the graph consistency check passed in the final suite.
- CSS rebuilt twice with `npm run build:css`; the second build was byte-stable.
- JavaScript syntax checks and `git diff --check`: passed.
- Ruff: **not run**, because `No module named ruff` in the existing virtual environment.

### Live integration and rendered forms

**Not verified in this environment.** Both `tools/snipeit_seed.py` and `tools/snipeit_probe.py` failed with `WinError 10061` (connection refused). The latest probe report records 0/11 environmental failures; this must not be read as a regression result or passing live evidence. Restart Snipe-IT, seed TEST data, then rerun the probes and `tools/v2_verify_all.py` before deployment.

LibreOffice, `soffice`, and `pdftoppm` are unavailable. `tools/check_pdf_render.py` therefore reports `FAIL Mylo.docx` and `FAIL B.tech.docx`; real PDF conversion, page-count evidence, and rendered-form PNG inspection remain blocked. The DOCX filling tests use the real B.tech and Mylo templates, PDF conversion is covered with a fake runner, and Playwright verifies successful PDF print behavior plus the Word-download fallback. Install LibreOffice Writer and fonts as now documented in both deployment guides, then run the checker and render both PDFs for owner inspection.

### Captures

`docs/review/v2/p1-dashboard.png`, `polish-handover-case.png`, `polish-maintenance-case.png`, `device-history-light.png`, and `device-history-dark.png`. The case/device captures were inspected. The two specification files remain untracked and untouched.

### Owner actions still open

1. Start Snipe-IT and provide LibreOffice plus a PDF rasterizer, then rerun live integration and form-render verification.
2. Review the Mylo form branding and provide the missing Nexta template (`docs/OPEN_QUESTIONS.md`).
3. Confirm the accumulated git commits; only after that can `feature/v2-polish` be committed and pushed. No merge is permitted.


Date: 2026-11-25
Branch: `feature/v2-handover-maintenance`
Baseline commit verified: `7271274` (Phase 07)  
Environment: real local Snipe-IT at `http://localhost:8081`, fresh portal DB at `data/verify_v2.db`.

## Live scenarios

| Scenario | Result | Evidence read back from Snipe-IT / portal |
|---|---|---|
| S1 Full handover | PASS | Outcome `complete`; `TEST-SN-0001` assigned to `test.btech1`, status `Deployed`; signed PNG listed in the asset files; generated DOCX contains the engineer name. |
| S2 Company mismatch | PASS | `company_mismatch`; `TEST-SN-0003` remained unassigned with status `Ready to deploy`. |
| S3 Recipient absent from Snipe-IT | PASS | First outcome `not_complete` with missing recipient parts; after selecting `test.nexta1`, outcome `complete`. |
| S4 No recipient | PASS | Outcome `ready`; the case appeared in the handover dashboard ready rows. |
| S5 Recipient items | PASS | `TEST-SN-0005` was checked in and its assignee was cleared in Snipe-IT. |
| S6 Maintenance flow | PASS | Two cases sent to `TEST-Vendor`; maintenance dashboard total was 2; first receive became `Ready to deploy` while the second stayed `Maintenance`; second receive succeeded. |
| S7 Separation | PASS | Handover dashboard contained no maintenance case and maintenance data contained no handover case. |
| S8 Failure handling | PASS | Invalid Snipe-IT asset id returned a clear one-line HTTP 422 error, not HTTP 500. |

**Result: 8/8 live scenarios PASS.** Run again with `python tools/v2_verify_all.py` while the portal is running on port 8080.

## Probe and automated checks

- Real Snipe-IT probe: **11/11 PASS** (`python tools/snipeit_probe.py`).
- Phase 05 + Phase 07 UI contracts: **4 passed**.
- Architecture rules: **30 passed**.
- Full suite before the final regression test: **507 passed, 13 skipped, 2 xfailed, 1 failed, 3 errors**. The one failure was a stale generated Principle visual and was regenerated immediately afterwards; `tests/test_principles_visual.py` then passed **6/6**. The three errors remain the known e2e setup `HTTP 503 Service Unavailable` responses.
- Final non-e2e suite: **509 passed, 13 skipped, 2 xfailed**.
- Ruff was not available in the environment (`No module named ruff`).
- Review screenshots: `docs/review/v2/` — handovers, handover case, maintenance, and maintenance devices at 1440 px and 390 px in light and dark themes.

No Snipe-IT token or other secret is recorded in this report.

## Round 2

Date: 2026-11-25
Branch: `feature/v2-handover-maintenance`
Environment: real local Snipe-IT at `http://localhost:8081`, isolated Round 2 portal DB at `data/verify_r2_round2.db`.

| Scenario | Result | Evidence read back from Snipe-IT / portal |
|---|---|---|
| S1 Full handover | PASS | Outcome `complete`; `TEST-SN-0001` assigned to `test.btech1`, status `Deployed`; signed PNG listed in the asset files; generated DOCX contains the engineer name. |
| S2 Company mismatch (Round 2 rule) | PASS | The recipient was stored, the response carried the warning `company_mismatch`, and the checkout to `test.btech1` succeeded (`TEST-SN-0003` assigned to `test.btech1`); the asset was checked back in during cleanup. |
| S3 Recipient absent from Snipe-IT | PASS | First outcome `not_complete` with missing recipient parts; after selecting `test.nexta1`, outcome `complete`. |
| S4 No recipient | PASS | Outcome `ready`; the case appeared in the handover dashboard ready rows. |
| S5 Recipient items | PASS | `TEST-SN-0005` was checked in and its assignee was cleared in Snipe-IT. |
| S6 Maintenance flow | PASS | Two cases sent to `TEST-Vendor`; maintenance dashboard total was 2; first receive became `Ready to deploy` while the second stayed `Maintenance`; second receive succeeded. |
| S7 Separation | PASS | The handover dashboard returns handover blocks only; the maintenance dashboard returns maintenance blocks only. |
| S8 Failure handling | PASS | Invalid Snipe-IT asset id returned a clear one-line HTTP 422 error, not HTTP 500. |

**Result: 8/8 live scenarios PASS.** Verified 2026-11-25 using an isolated portal DB and temporary minimal B.tech/Nexta form fixtures. The owner templates were not present in `forms/`; the fixtures were not committed. Run again with `python tools/v2_verify_all.py` while the portal is running on port 8080 and the required form templates are installed.

Recipient probe against the real Snipe-IT: **9/9 PASS** (`python tools/v2_probe_handover_recipient.py`). It proves the Round 2 rule end to end: choosing `test.mylo1` for the B.tech device `TEST-SN-0001` is accepted with the warning `company_mismatch`, the event `company_mismatch_warning` is written, and the checkout to that Mylo user succeeds in Snipe-IT (`assigned_to` read back). The result is appended to `docs/snipeit-integration-report.md` under "Round 2".

Note on form templates: `forms/` held no Word templates in this environment, so the live run used minimal generated templates that contain `{{ENGINEER}}` after `المهندس :` (B.tech, Nexta) and after `توقيع مهندس الدعم الفني:` (Mylo). They were not committed; saving the owner's real templates in `forms/` is still open.

### Round 2 final check (2026-11-25)

- Focused suite: `pytest tests -q -k "company or recipient or checkout or pending"` — **101 passed, 4 skipped, 510 deselected**.
- Dashboard: `pytest tests/test_dashboard.py -q` — **34 passed**. Architecture: `pytest tests/test_architecture_rules.py -q` — **30 passed**.
- CSS: `npm.cmd run build:css` — passed. Ruff could not run because the environment has no `ruff` module.
- Full live scenario runner: **8/8 PASS** on the isolated database. The recipient probe against real Snipe-IT: **9/9 PASS**, including mismatch warning, successful checkout and assignee read-back.
- Playwright review: full and empty data passed at 390/1440 px in light/dark themes, with no horizontal overflow or page errors. Eight captures are in `docs/review/v2/dashboard-*.png`.
- The full pytest attempt did not complete: after several failures appeared, pytest's Windows process ended with an access violation during collection/setup. Do not treat the full suite as green. The focused Round 2, dashboard and architecture suites above completed successfully.
- The owner database was only dry-run inspected (36 handovers, 324 stages, 265 events, 6 documents, 23 agent reports, 5 maintenance rows; 12 files). No owner data was deleted. The live scenarios ran on an isolated database; TEST Snipe-IT assets were reseeded after the probes.
