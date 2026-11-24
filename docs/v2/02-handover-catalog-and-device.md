# Phase 02: Handover catalog, migration, create case, device status

Prerequisite: `HANDOFF-V2.md` says `PHASE 01 DONE`. Read `00-README` A and B1 only.

Goal: a Handover case has the new list of parts, stores the device facts it read from Snipe-IT (company, model, category), and the device-status part works against Snipe-IT.

## Step 2.1 New operation list (domain, pure)
Files: `app/domain/catalog.py`, `app/domain/stages.py`.
1. Add enum members to `Operation`: `DEVICE_STATUS = "device_status"`, `RECIPIENT_ITEMS = "recipient_items"`.
2. Set `HANDOVER_OPERATIONS` (this order is the screen order) to:
   `DEVICE_STATUS, AGENT_REPORT, SOFTWARE_CHECK, REPORT_PRINTED, RECIPIENT_CHECK, RECIPIENT_ITEMS, CHECKOUT, DOCUMENT_SCANNED, DOCUMENT_PUSHED`.
   Keep the removed members (`DEVICE_PREPARED`, `USER_SIGNED_IN`, `USER_SIGNED`) in the enum only so old database rows still load; they are just no longer in the tuple.
3. Add titles in `OPERATION_TITLES` (short labels): `Device status`, `Recipient items`. Update lanes (`lanes_for`) so the lanes are: `Device` = DEVICE_STATUS, AGENT_REPORT, SOFTWARE_CHECK; `Form` = REPORT_PRINTED; `Recipient` = RECIPIENT_CHECK, RECIPIENT_ITEMS, CHECKOUT; `Paper` = DOCUMENT_SCANNED, DOCUMENT_PUSHED.
4. Add `READY = "ready"` to `HandoverStatus` in `stages.py` (active status; do NOT add it to `INACTIVE_CASE_STATUSES`).
Find affected code: `grep -rn "DEVICE_PREPARED\|USER_SIGNED_IN\|USER_SIGNED\b" app templates static tests | cut -c1-110`. Fix each usage by removing it from active flows. Existing tests that list the old 10 operations must be updated to the new 9 (allowed: the spec changed). Write the list of changed tests in `HANDOFF-V2.md`.
Check: `pytest tests/test_domain_rules.py tests/test_independent_operations.py tests/test_stall_by_age.py -q` green after your test edits.

## Step 2.2 Migration 0007 (device facts and recipient mode)
Create `alembic/versions/0007_handover_v2.py` (`down_revision = "0006_maintenance_priority"`; check the real id with `alembic heads`). Add nullable string columns on table `handovers`:
`device_company` (120), `device_model` (120), `device_category` (120), `snipeit_status_name` (80), `recipient_mode` (20: `snipeit`, `none`, `not_in_snipeit`), `recipient_free_name` (200), `recipient_free_email` (200). Add index on `device_company`. Mirror them in `app/db/models/handover.py`.
Use `op.batch_alter_table` (SQLite). `downgrade` drops them.
Check on a THROW-AWAY database: `DATABASE_URL=sqlite+aiosqlite:///./data/tmp_v2.db alembic upgrade head` then `alembic downgrade -1` then `upgrade head`; all succeed. Delete the file after.

## Step 2.3 Create a handover from the real Snipe-IT device
File: `app/services/handovers.py` (`create`) and `app/routers/handovers.py` (`POST ""`).
For `kind == handover`: after validating the serial, the service asks Snipe-IT (`get_asset_by_serial`) and stores `snipeit_asset_id`, `snipeit_asset_tag`, `device_company`, `device_model`, `device_category`, `snipeit_status_name`. If the serial is not found in Snipe-IT: raise a clear error, HTTP 422, message `Serial not found in Snipe-IT` and create NOTHING. If Snipe-IT is unreachable: HTTP 503 with a one-line message.
Inject the client the same way the other endpoints do (look at how `checkout` gets it: `grep -n "SnipeItClient\|snipeit_client" app/routers/handovers.py | head`).
Tests (fake client from `tests/fakes`): found creates a case with company/model; not found creates nothing; unreachable gives 503.
Check: `pytest tests/test_handover_service.py tests/test_handovers_api.py -q` green.

## Step 2.4 Device status part
Config: add to `app/config.py` `SNIPEIT_STATUS_READY = os.getenv("SNIPEIT_STATUS_READY", "Ready to deploy")` (a status label NAME).
Endpoints in `app/routers/handovers.py`:
- `GET /api/snipeit/status-labels` (in `app/routers/snipeit.py`): returns `[{id, name}]` from `list_status_labels`.
- `POST /api/handovers/{id}/device-status` body `{"status_label_id": int | null}`.
  - With an id: call `update_asset_status`, then re-read the asset.
  - Always: refresh `snipeit_status_name` and `device_company` from Snipe-IT.
  - Record operation `DEVICE_STATUS` through `record_operation`: `passed` when the name equals `SNIPEIT_STATUS_READY` (case-insensitive), otherwise `failed` with reason `Status is <name>`. A Snipe-IT error records `failed` with the error line; it never raises to the user as a crash.
Tests: ready status passes; "Maintenance" status fails with reason; changing the label then passes.
Check: `pytest tests/test_handovers_api.py -q -k device_status` green.

## Step 2.5 Live check against real Snipe-IT (REQUIRED)
Write `tools/v2_probe_handover_device.py` that, with the app code (not curl), creates a case for `TEST-SN-0001`, asserts `device_company == "B.tech"`, calls device-status with the `Maintenance` label (expects `failed`), then with `Ready to deploy` (expects `passed`), and cancels the case. Run it.
Check: prints 4 PASS lines. Append the result to `docs/snipeit-integration-report.md` under "Phase 02".

## Step 2.6 Close the phase
Full suite once. Update `HANDOFF-V2.md`: `PHASE 02 DONE`, changed tests, test counts. Commit.
Next file: `03-handover-recipient.md`.
