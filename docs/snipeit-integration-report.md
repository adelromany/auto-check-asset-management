# Snipe-IT integration report

Live instance: `deploy/snipeit-dev` (Snipe-IT v8), local only.
Probe: `python tools/snipeit_probe.py` (uses `app/clients/snipeit.py`).
No tokens or secrets are recorded here.

## Phase 01

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | whoami | PASS | user=admin |
| 2 | asset by serial has company/model/category/status | PASS | company=B.tech model=Latitude 5440 status=Ready to Deploy |
| 3 | status labels include Ready to deploy and Maintenance | PASS | Deployed, Maintenance, Pending, Ready to Deploy, Archived |
| 4 | update asset status and restore | PASS | Maintenance -> Ready to deploy |
| 5 | search_users returns company | PASS | 2 users, all with company |
| 6 | list_user_assets includes TEST-SN-0005 | PASS | TEST-SN-0005 present |
| 7 | checkin TEST-SN-0005 clears assignee | PASS | assignee cleared and restored |
| 8 | checkout TEST-SN-0001 to test.btech1 | PASS | assigned to test.btech1 (id 4), status=Deployed |
| 9 | upload file and list it | PASS | probe-41508.png listed (7 files) |
| 10 | cleanup checkin and Ready to deploy | PASS | checked in, Ready to deploy |
| 11 | error shapes (not found, bad token) | PASS | SnipeItNotFound + SnipeItAuthError |

## Round 2

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | user search marks Mylo false and B.tech true | PASS | mylo={'id': 6, 'name': 'TEST Mylo1', 'email': 'test.mylo1@example.test', 'username': 'test.mylo1', 'company': 'Mylo', 'same_company': False} btech={'id': 5, 'name': 'TEST Btech2', 'email': 'test.btech2@example.test', 'username': 'test.btech2', 'company': 'B.tech', 'same_company': True} |
| 2 | Mylo recipient is accepted with a company warning | PASS | status='passed' warnings=['company_mismatch'] events=['handover_created', 'recipient_changed', 'company_mismatch_warning', 'operation_recorded', 'operation_recorded'] |
| 3 | device is checked out to the Mylo user with a warning | PASS | stage='passed' assignee=6 expected=6 |
| 4 | B.tech recipient is accepted | PASS | status='passed' |
| 5 | recipient items include TEST-SN-0005 | PASS | items=[{'asset_id': 7, 'asset_tag': 'TEST-SN-0005', 'serial': 'TEST-SN-0005', 'model': 'Latitude 5440', 'status': 'Deployed'}] |
| 6 | TEST-SN-0005 is checked in | PASS | outcome='checked_in' assignee=None |
| 7 | recipient items are confirmed | PASS | status='passed' detail={'none': True, 'checked_in': ['TEST-SN-0005']} |
| 8 | device is checked out with Deployed status | PASS | stage='passed' assignee=5 status='Deployed' |
| 9 | case cancelled (cleanup) | PASS |  |
