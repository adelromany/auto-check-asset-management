# HANDOFF V2 - working memory

Branch: `feature/v2-handover-maintenance` (from `origin/fix/ui-recovery`, tip 265b26c).

STEP 1.1 DONE Snipe-IT dev stack already running (snipeit-dev-snipeit-1, db healthy); `curl http://localhost:8081/login` = 200.
STEP 1.2 DONE `.env` has SNIPEIT_URL/SNIPEIT_TOKEN (git-ignored); `GET /api/v1/users/me` returns admin.
STEP 1.3 DONE `tools/snipeit_seed.py` created; first run created companies/status/category/manufacturer/model/assets/users and checked out TEST-SN-0005 to test.btech2; second run prints only `exists` lines. Added a `Deployed` status label (deployable, default) because the dev instance had none and the checkout check needs it. Aligned pre-existing TEST-SN-0001 to B.tech / Latitude 5440.
STEP 1.4 DONE client DTOs extended (asset company_id/company/status_id, user company_id/company), `find_status_label_id` added, `checkout_asset_to_user` accepts optional `status_id` (Snipe-IT keeps the old status otherwise); fake updated; `pytest tests/test_snipeit_client.py -q` = 30 passed.
STEP 1.5 DONE `tools/snipeit_probe.py` = 11/11 PASS against the real dev instance; report at `docs/snipeit-integration-report.md`.
STEP 1.6 DONE `tests/test_snipeit_live.py` extended with 4 V2 tests (asset company, status roundtrip, users company, checkout->Deployed); `SNIPEIT_LIVE=1 pytest tests/test_snipeit_live.py -q` = 10 passed; without the variable 10 skipped. Environment variables: accepts `SNIPEIT_LIVE` or `SNIPEIT_LIVE_TEST`, loads `.env` only in live mode.
PHASE 01 DONE - 11 PASS lines, unit tests green, report committed.
Next: `02-handover-catalog-and-device.md` (read only its steps; `00-README` A and B1).
