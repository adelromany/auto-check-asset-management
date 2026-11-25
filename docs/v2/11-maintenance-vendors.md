# Round 3: Maintenance vendors (add, edit, remove)

Branch: `feature/v2-handover-maintenance`. Rules: `docs/v2/00-README-rules-and-spec.md` section A. Put this file in `docs/v2/`. Do it AFTER Round 1 and Round 2 are finished (`09` and `10`), unless the owner says otherwise. Track it in `HANDOFF-V2.md` as "ROUND 3".

Problem: there is no clear way to add a maintenance vendor. Phase 06 only has a vendors API, and phase 07 only has a small "+ New vendor" link inside the Send batch drawer. Vendors are internal to the portal (Snipe-IT has no suppliers here), so no Snipe-IT calls are involved.

## Step V1 Look first (small reads)
`grep -n "maintenance_destinations\|class .*Destination" -r app alembic | cut -c1-120` and read the model and the existing repository functions. List the existing columns in `HANDOFF-V2.md`. Reuse; do not create a second vendors table.

## Step V2 Migration `0011_vendors.py`
Add to `maintenance_destinations` only the missing columns: `contact_name` (120), `phone` (40), `email` (200), `notes` (500), `is_active` (bool, default true, not null). Index on lower(name) unique (case-insensitive unique name). Use `batch_alter_table`. Check upgrade, downgrade -1, upgrade on a throw-away database.

## Step V3 Backend
- `GET /api/maintenance/vendors?include_inactive=false`: returns `{id, name, contact_name, phone, email, notes, is_active, at_vendor_now, total_sent, avg_days}` where the three counters come from maintenance cases (grouped query, no loop): devices currently at this vendor, devices ever sent, average days from sent to returned (null when none).
- `POST /api/maintenance/vendors`: body `name` (required, trimmed, 2 to 120 chars) and the optional fields. Duplicate name (case-insensitive) gives 409 `Vendor already exists` with the existing id.
- `PATCH /api/maintenance/vendors/{id}`: any of the fields, including `is_active`. Renaming keeps old cases linked (they reference the id).
- `DELETE /api/maintenance/vendors/{id}`: allowed only when no case references it; otherwise 409 `Vendor has devices. Deactivate instead`.
- Inactive vendors do not appear in the selects for new sends or planned vendors, but old cases still show their name.
- Email, if given, must contain `@`; phone free text. No validation beyond that.
Tests in `tests/test_maintenance_api.py`: create, duplicate (different case), edit, deactivate hides from select lists, delete unused works, delete used is 409, counters are right with seeded cases.
Check: `pytest tests/test_maintenance_api.py -q -k vendor` green.

## Step V4 UI: Vendors page `/maintenance/vendors`
- Add it to the Maintenance group in the left rail and the bottom bar: **Vendors** (after Devices).
- Header: title **Vendors**, button **Add vendor**, toggle **Show inactive**.
- A card per vendor (grid, 3 columns desktop, 1 on phone): name, three small numbers (`At vendor now`, `Sent`, `Avg days`), contact line (name, phone, email with `tel:` and `mailto:` links), buttons **Edit** and **Deactivate** (or **Activate**), and **Delete** shown only when the vendor has no devices.
- **Add vendor** and **Edit** open the same drawer: fields Name, Contact, Phone, Email, Notes, button **Save**. Errors as one plain line under the field (for example `Vendor already exists`).
- Empty state: one big button **Add vendor** and nothing else.
- Short labels only; no explanatory sentences.

## Step V5 Add a vendor from where it is needed
- In **Send batch** drawer (phase 07, step 7.4) and in the **Add device** card (planned vendor select): the select ends with the option **+ New vendor**. Choosing it opens the same drawer from step V4; after Save the select is refreshed and the new vendor is selected, and the engineer continues without leaving the screen.
- If there are no active vendors, the **Send batch** button opens the vendor drawer first with a plain line `Add a vendor first`.

## Step V6 Dashboard link
On the maintenance dashboard (phase 07, step 7.6) a vendor name in **By vendor** and in the devices table links to its card on `/maintenance/vendors` (anchor `#vendor-<id>`).

## Step V7 Tests and checks
Playwright: add a vendor from the page; add one from the Send batch drawer and send with it; edit the name and see it in an old case; deactivate and see it disappear from the select; delete is hidden for a vendor with devices; no horizontal scroll at 390 and 1440 px, both themes.
Add scenario S14 to `tools/v2_verify_all.py`: create vendor through the API, send a test device with it (live Snipe-IT status checks as in S6), deactivate, confirm it is not selectable, confirm the old case still shows the name; clean up.
Full suite, `ruff`, architecture test. Commit and push. Final message to the owner: commit id, what was added, screenshots path.

If you reach about 25 tool calls in one chat, write the state into `HANDOFF-V2.md` and stop; the owner will start a new chat with the START MESSAGE from `00-README` plus the line: `Continue ROUND 3 from docs/v2/11-maintenance-vendors.md`.
