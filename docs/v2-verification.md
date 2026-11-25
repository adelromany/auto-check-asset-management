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
