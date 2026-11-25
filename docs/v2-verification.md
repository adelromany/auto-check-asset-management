# V2 Final Verification

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
