# Fix: a device sent to a vendor appears in both "With IT" and "At vendor"

Branch: `feature/v2-handover-maintenance`. Rules: `docs/v2/00-README-rules-and-spec.md` section A. Put this file in `docs/v2/`. Do it after the current round, or first if the owner says so. Track as "FIX 12" in `HANDOFF-V2.md`.

Rule that must hold everywhere: a maintenance device is in EXACTLY ONE state: `with_it`, `at_vendor`, or `returned`. The state is derived from the recorded operations by ONE pure function (`derive_maintenance_state` in `app/domain/maintenance_rules.py`). No screen, query or dashboard may compute it differently.

## Step 1 Reproduce first (tests, no code changes yet)
In `tests/test_maintenance_state.py` write tests and run them; list in `HANDOFF-V2.md` which fail:
1. `derive_maintenance_state` returns exactly one value for every combination of RECEIVED, SENT_OUT, RETURNED (table-driven, including the odd ones: SENT_OUT passed with RECEIVED pending; RETURNED passed with SENT_OUT pending).
2. After batch send, `GET /api/maintenance/cases?state=with_it` does NOT contain the case and `state=at_vendor` does.
3. After batch receive the case is only in `returned`.
4. Dashboard: after send, the device counts in `in_maintenance` and NOT in `needs`; the totals of the two never include the same case id.
5. Two active maintenance cases for the same device (same serial) are impossible: the second `POST /api/maintenance/cases` returns 409. (A second case is the most likely reason one physical device shows twice.)
6. Sending the same case twice: the second send fails for that case with `Not with IT` and changes nothing.

## Step 2 Find the cause (small reads)
Check these in order and write the finding in `HANDOFF-V2.md`:
- `grep -n "with_it\|at_vendor" -r app static templates | cut -c1-120`: does any query or JS filter use its own condition (for example "no returned date" or "planned vendor is empty") instead of the derived state?
- The Devices screen JS (`static/js/maintenance_devices.js`): after Send batch, does it remove rows from the With IT table using the server response, or does it only add to At vendor? Does it keep a local copy of the lists?
- Are there two cases for that serial in the test database? (`SELECT device_serial, count(*) ... WHERE kind='maintenance' GROUP BY device_serial HAVING count(*)>1`).
- Does `with_it` include cases whose `SENT_OUT` stage is `not_done` or `failed` rather than missing?

## Step 3 Fix
- One shared function in the repository layer, `case_state_filter(state)`, used by the list endpoint, the dashboard and the counts. It selects by the derived state rules (RECEIVED passed and SENT_OUT not passed = with_it; SENT_OUT passed and RETURNED not passed = at_vendor; RETURNED passed = returned). Add a unit test that the three results never overlap for a seeded set of 30 cases in mixed states.
- Enforce one active maintenance case per device in the service and with a partial unique index (like the handover rule): unique on normalized serial where kind is maintenance and the case is not returned or cancelled.
- UI: after Send batch or Receive batch, re-fetch BOTH tables from the server (do not patch local arrays). A successful row disappears from the source table because the server no longer returns it.
- Old duplicate rows already in the database: write the SQL check from step 2 into `tools/check_duplicates.py` (read-only, prints the duplicates) and tell the owner to run it; do not delete anything yourself.
Check: all tests from step 1 green; full suite green.

## Step 4 Live check (real Snipe-IT) and browser
- Add to scenario S6 in `tools/v2_verify_all.py`: after batch send, assert the case id is absent from `state=with_it` and present in `state=at_vendor`; after receive, present only in `returned`; the dashboard `needs` and `in_maintenance` case id lists are disjoint.
- Playwright: add a device, send it, assert the row is only in the At vendor tab; receive it, assert it is only in Returned.
Commit and push. Final message to the owner: the cause found, the commit id, and the result of `tools/check_duplicates.py`.
