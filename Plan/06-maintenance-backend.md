# Phase 06: Maintenance backend (devices, batches, dashboard data)

Prerequisite: `HANDOFF-V2.md` says `PHASE 05 DONE`. Read `00-README` A and B2.

Goal: the backend for the Maintenance section, fully separate from Handover (no shared numbers). Every Snipe-IT action is proven live in step 6.9.

Terms: a maintenance case is a `Handover` row with `kind = "maintenance"`. Device states: With IT (received, not sent), At vendor (sent, not returned), Returned (back, Ready to deploy set).

## Step 6.1 Operations list for maintenance (domain, pure)
`app/domain/catalog.py`: `MAINTENANCE_OPERATIONS` in screen order:
`RECEIVED, DIAGNOSIS, SNIPEIT_STATUS, TAKEN_BACK, SENT_OUT, RETURNED, READY_STATUS`.
- Add the missing enum members: `SNIPEIT_STATUS = "snipeit_status"` (set Maintenance in Snipe-IT), `TAKEN_BACK = "taken_back"` (removed from its user in Snipe-IT; optional, may stay `not_done`), `READY_STATUS = "ready_status"` (set Ready to deploy after return). Keep any existing member that is already used; look first: `grep -n "RECEIVED\|DIAGNOSIS\|SENT_OUT\|RETURNED\|SNIPEIT_STATUS" app/domain/catalog.py`.
- Titles (short): `Received`, `Reason`, `Status Maintenance`, `Taken back`, `Sent`, `Returned`, `Status Ready`.
- `app/domain/maintenance_rules.py`: `derive_maintenance_state(states)` returns `with_it` when RECEIVED passed and SENT_OUT not passed; `at_vendor` when SENT_OUT passed and RETURNED not passed; `returned` when RETURNED passed. Add `days_in_maintenance(received_date, returned_date, today) -> int` (calendar days, minimum 0; open cases count to today).
Tests in `tests/test_maintenance_rules.py`: each state; days for open and closed cases.
Check: `pytest tests/test_maintenance_rules.py tests/test_domain_rules.py -q` green.

## Step 6.2 Migration 0008 (device snapshot and reasons)
`alembic/versions/0008_maintenance_v2.py`:
- Table `maintenance_info` gets nullable `received_date` (date), `reason_text` (300). (Use `batch_alter_table`.)
- Table `diagnosis_categories`: seed these names if missing (data migration, idempotent by name): `Screen`, `Keyboard`, `Battery`, `Charger / power`, `Won't power on`, `Overheating`, `Slow`, `Disk`, `RAM`, `Motherboard`, `Network`, `Ports`, `Speaker / mic / webcam`, `Hinge / body`, `Liquid damage`, `OS / software`, `BIOS / boot`, `Other`.
Check on a THROW-AWAY database: upgrade, downgrade -1, upgrade; delete the file.

## Step 6.3 Config for labels
`app/config.py`: `SNIPEIT_STATUS_MAINTENANCE = os.getenv("SNIPEIT_STATUS_MAINTENANCE", "Maintenance")` and reuse `SNIPEIT_STATUS_READY` from phase 02. The existing `SNIPEIT_STATUS_*` id-based names stay only if still used; otherwise remove them and list that in `HANDOFF-V2.md`. Statuses are looked up by NAME through `find_status_label_id` (phase 01).
Check: `pytest tests/test_config.py -q` (or the nearest config test) green.

## Step 6.4 Add device (the case is born here)
`POST /api/maintenance/cases` body `{"serial": "...", "reason_id": int | null, "reason_text": "..." | null, "planned_vendor_id": int | null}`:
1. Ask Snipe-IT for the serial; not found gives 422 `Serial not found in Snipe-IT`; unreachable 503. Store `snipeit_asset_id`, tag, `device_company`, `device_model`, `device_category`, `snipeit_status_name`, and the current assignee name in the case detail.
2. A device may have only ONE active maintenance case; a second returns 409 with the existing case id.
3. Create the case with `received_date = today`, record `RECEIVED` passed. If a reason is given record `DIAGNOSIS` passed (`reason_text` required when the reason is `Other`, max 300). If a planned vendor is given store it in `destination_id` (this is only a plan; `SENT_OUT` stays pending).
Also `GET /api/maintenance/device-lookup?serial=` returns the Snipe-IT snapshot (`model`, `company`, `status`, `assigned_to`) without creating anything (the screen shows it as the engineer types).
Tests with the fake client: creates with snapshot; unknown serial; duplicate active case; Other without text rejected.
Check: `pytest tests/test_maintenance_api.py -q -k "create or lookup"` green.

## Step 6.4b Reasons list
`GET /api/maintenance/reasons` returns the ordered list of reasons (`Other` last). Reuse the existing categories endpoint if it exists; keep one route only.

## Step 6.5 Set Maintenance status and take back from user
- `POST /api/maintenance/cases/{id}/set-status`: calls `update_asset_status` with the id found from `SNIPEIT_STATUS_MAINTENANCE`, re-reads the asset, records `SNIPEIT_STATUS` passed when the name matches, else failed with the line. If the label name does not exist in Snipe-IT: 422 `Status label "Maintenance" not found in Snipe-IT`.
- `POST /api/maintenance/cases/{id}/take-back`: only when the asset is assigned; calls the existing check-in logic (`checkin_asset`), re-reads, records `TAKEN_BACK` passed. If the device is not assigned, record `TAKEN_BACK` as `not_done` with reason `Not assigned` and return 200.
Both are independent of each other and of the reason.
Tests: both happy paths; Snipe-IT error records failed and returns a clear body; not assigned.
Check: `pytest tests/test_maintenance_api.py -q -k "set_status or take_back"` green.

## Step 6.6 Vendors list (internal)
Reuse the existing destinations endpoints: `GET/POST /api/maintenance/vendors` (name only, unique, trimmed). Do not add suppliers in Snipe-IT.
Check: `pytest tests/test_maintenance_api.py -q -k vendor` green.

## Step 6.7 Batch send and batch receive
- `POST /api/maintenance/batches/send` body `{"case_ids": [..], "vendor_id": int, "sent_date": "YYYY-MM-DD"}`: for each case (must be with IT) record `SENT_OUT` passed with the vendor and date. Returns `[{case_id, ok, error}]`. One bad case never blocks the others.
- `POST /api/maintenance/batches/receive` body `{"case_ids": [..], "returned_date": "YYYY-MM-DD"}`: for each case (must be at vendor) record `RETURNED` passed with the date, then set the Snipe-IT status to `SNIPEIT_STATUS_READY` and record `READY_STATUS` (passed or failed with the Snipe-IT line). Returns per-case results. A Snipe-IT failure keeps `RETURNED` and leaves `READY_STATUS` failed; `POST /api/maintenance/cases/{id}/ready-status` retries only that.
- Validation: dates not in the future, `returned_date >= sent_date`, at most 100 cases per call.
Tests: all ok; one case in the wrong state fails while the others pass; Snipe-IT failure on one case; retry.
Check: `pytest tests/test_maintenance_api.py -q -k batch` green.

## Step 6.8 Dashboard data (maintenance only)
`app/services/dashboard.py` + `GET /api/dashboard/maintenance`:
```
{needs: {total, by_model[], by_company[], by_vendor[]},
 in_maintenance: {total, by_model[], by_company[], by_vendor[], avg_days},
 devices: [{case_id, serial, model, company, vendor, state, days, reason}]}
```
- `needs` = cases with state `with_it` (received, not yet sent). Its vendor group is the planned vendor or `Not assigned`.
- `in_maintenance` = cases with state `at_vendor`.
- `days` per device uses `days_in_maintenance`. `avg_days` over `in_maintenance`.
- Never count handover cases; never mix numbers with the handover dashboard.
- `GET /api/maintenance/cases?state=with_it|at_vendor|returned&company=&model=&vendor_id=` for the lists.
Tests: three companies, two vendors, mixed states; groups add up to the totals.
Check: `pytest tests/test_dashboard.py -q -k maintenance` green.

## Step 6.9 Live end to end for maintenance (REQUIRED)
`tools/v2_probe_maintenance.py`, real Snipe-IT, app code, `TEST-` data:
1. Lookup `TEST-SN-0004` (Nexta): company is `Nexta`.
2. Create case with reason `Screen`; set-status: Snipe-IT shows `Maintenance`.
3. `TEST-SN-0005` (assigned to `test.btech2`, if still assigned; otherwise check it out first): create case, take-back: Snipe-IT shows no assignee; set-status.
4. Create a vendor `TEST-Vendor`; batch send both; dashboard `in_maintenance.total == 2`, by vendor `TEST-Vendor 2`.
5. Batch receive only `TEST-SN-0004`: Snipe-IT status `Ready to deploy`; `TEST-SN-0005` is still `Maintenance`.
6. Receive the second; both Ready to deploy. Cleanup: close cases, delete the test vendor, leave assets Ready to deploy.
Check: all PASS; append to `docs/snipeit-integration-report.md` under "Phase 06".

## Step 6.10 Close the phase
Full suite once. `HANDOFF-V2.md`: `PHASE 06 DONE`. Commit.
Next file: `07-maintenance-ui.md`.
