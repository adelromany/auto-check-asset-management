# Phase 03: Recipient, company rule, recipient's current items

Prerequisite: `HANDOFF-V2.md` says `PHASE 02 DONE`. Read `00-README` A and B1 (parts 5, 6, 7).

Goal: the recipient part works with a Snipe-IT user, with "None for now", or with "Not in Snipe-IT yet"; the company rule is enforced on the server; the recipient's current items can be reviewed and taken back; the checkout part uses the same rules.

## Step 3.1 Company rule (pure domain)
File `app/domain/handover_rules.py` (or a new `app/domain/company_rules.py` if the file is long). Add:
```python
def normalize_company(name: str | None) -> str:
    # casefold, keep only letters and digits: "B.tech" -> "btech"
def company_conflict(device_company: str | None, recipient_company: str | None) -> bool:
    # True only when BOTH are known and normalize to different values
def company_known(name: str | None) -> bool
```
Tests in `tests/test_domain_rules.py`: same names with different case or dots do not conflict; one side unknown does not conflict; `B.tech` vs `Mylo` conflicts.
Check: `pytest tests/test_domain_rules.py -q -k company` green.

## Step 3.2 User search that knows companies
`app/routers/snipeit.py`: `GET /api/snipeit/users?q=<text>&handover_id=<uuid>` returns up to 10 users: `{id, name, email, username, company, same_company: bool | null}`. `same_company` is `null` when a company is unknown, otherwise `not company_conflict(...)` against the case's `device_company`. Minimum query length 2. Never return more than these fields.
Tests with the fake client: same company true, other company false, unknown null.
Check: `pytest tests/test_handovers_api.py -q -k users_search` green.

## Step 3.3 Choose the recipient (three modes)
`POST /api/handovers/{id}/recipient`, body one of:
- `{"mode": "snipeit", "user_id": 12}`: fetch the user with `get_user`. If `company_conflict` is true: HTTP 422, `code = "company_mismatch"`, message `Recipient company differs from the device company`. Otherwise store `recipient_mode="snipeit"`, `recipient_snipeit_id/username/name/email`, clear the free fields. Record `RECIPIENT_CHECK` as `passed`. If the recipient's company is unknown, still pass but add `detail={"warning": "company_unknown"}`.
- `{"mode": "none"}`: clear every recipient field, `recipient_mode="none"`, record `RECIPIENT_CHECK` as `not_done` with reason `No recipient yet`; also record `RECIPIENT_ITEMS`, `CHECKOUT`, `DOCUMENT_SCANNED`, `DOCUMENT_PUSHED` untouched (they stay pending).
- `{"mode": "not_in_snipeit", "name": "...", "email": "..."}`: store the free fields (trim, max 200, email must contain `@`), `recipient_mode="not_in_snipeit"`, record `RECIPIENT_CHECK` as `not_done` with reason `Not in Snipe-IT yet`.
Changing the recipient later is allowed while the case is open: the service resets `RECIPIENT_ITEMS` and `CHECKOUT` to pending if they were passed (log one event `recipient_changed` with old and new name). Reuse existing helpers in `app/domain/recipient_identity.py` if they fit; do not duplicate.
Tests: snipeit same company passes; other company is rejected and stores nothing; none sets not_done; free mode stores; changing after checkout is rejected with a clear message (the device is already checked out).
Check: `pytest tests/test_handover_service.py tests/test_handovers_api.py -q -k recipient` green.

## Step 3.4 Recipient's current items
- `GET /api/handovers/{id}/recipient/items`: returns the Snipe-IT assets currently assigned to the recipient (`list_user_assets`), excluding this case's own device: `[{asset_id, asset_tag, serial, model, status}]`. Empty list when the mode is not `snipeit`.
- `POST /api/handovers/{id}/recipient/items/checkin` body `{"asset_ids": [..]}`: for each id call `checkin_asset` (reuse `checkin_assets` in `app/services/snipeit_ops.py`, look at its signature with `sed -n 347,380p`). Only ids that belong to the recipient's current items are accepted (otherwise 422). Returns one result per id (`ok` or an error line). Partial success is fine.
- `POST /api/handovers/{id}/recipient/items/confirm`: records `RECIPIENT_ITEMS` as `passed` with detail `{"checked_in": [serials], "kept": [serials]}`.
- When the recipient has NO other items, `RECIPIENT_ITEMS` passes automatically right after step 3.3 (detail `{"none": true}`).
Tests: list excludes the case's own device; checkin only for owned ids; auto-pass when empty; confirm passes with kept items.
Check: `pytest tests/test_handovers_api.py -q -k recipient_items` green.

## Step 3.5 Checkout rules (server side)
In the existing checkout flow (`checkout` in `app/services/snipeit_ops.py`, endpoint `POST /{id}/checkout`) add guards before calling Snipe-IT:
1. `recipient_mode` must be `snipeit`, else 422 `Choose a Snipe-IT recipient first`.
2. `company_conflict` again against the stored values, else 422 `company_mismatch`.
3. The device must not be checked out to someone else (re-read the asset). If it is, 422 with the current assignee name.
Do NOT require the other parts to be passed (independent operations), only these guards.
Tests for each guard (fake client) plus one happy path.
Check: `pytest tests/test_snipeit_write_ops.py tests/test_handovers_api.py -q -k checkout` green.

## Step 3.6 Live check against real Snipe-IT (REQUIRED)
Write `tools/v2_probe_handover_recipient.py` using the app code. Scenario with the seed data from phase 01:
1. Case for `TEST-SN-0001` (B.tech). Search users `test.` and assert `test.mylo1` has `same_company == False` and `test.btech1` has `True`.
2. Choose `test.mylo1`: expect `company_mismatch`. Choose `test.btech2`: expect passed.
3. Items of `test.btech2` include `TEST-SN-0005`; take it back; verify in Snipe-IT it has no assignee; confirm items.
4. Checkout to `test.btech2`; verify in Snipe-IT `assigned_to` and status Deployed.
5. Cleanup: check the device back in and set it to Ready to deploy; cancel the case.
Check: all PASS. Append the result to `docs/snipeit-integration-report.md` under "Phase 03".

## Step 3.7 Close the phase
Full suite once. `HANDOFF-V2.md`: `PHASE 03 DONE`. Commit.
Next file: `04-handover-form-and-outcome.md`.
