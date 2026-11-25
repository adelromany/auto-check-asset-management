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
| 9 | upload file and list it | PASS | probe-31444.png listed (4 files) |
| 10 | cleanup checkin and Ready to deploy | PASS | checked in, Ready to deploy |
| 11 | error shapes (not found, bad token) | PASS | SnipeItNotFound + SnipeItAuthError |

## Phase 02

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | case created from the real device | PASS |  |
| 2 | case stores company, model and category | PASS | company='B.tech' model='Latitude 5440' category='Laptop' |
| 3 | status labels found (Maintenance, Ready to deploy) | PASS | maintenance=4 ready=2 |
| 4 | Maintenance label fails the device-status part | PASS | status='failed' reason='Status is Maintenance' |
| 5 | Ready to deploy passes the device-status part | PASS | status='passed' reason=None |
| 6 | case cancelled (cleanup) | PASS |  |

## Phase 03

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | user search marks Mylo false and B.tech true | PASS | mylo={'id': 6, 'name': 'TEST Mylo1', 'email': 'test.mylo1@example.test', 'username': 'test.mylo1', 'company': 'Mylo', 'same_company': False} btech={'id': 5, 'name': 'TEST Btech2', 'email': 'test.btech2@example.test', 'username': 'test.btech2', 'company': 'B.tech', 'same_company': True} |
| 2 | Mylo recipient is rejected by the company rule | PASS |  |
| 3 | B.tech recipient is accepted | PASS | status='passed' |
| 4 | recipient items include TEST-SN-0005 | PASS | items=[{'asset_id': 7, 'asset_tag': 'TEST-SN-0005', 'serial': 'TEST-SN-0005', 'model': 'Latitude 5440', 'status': 'Ready to Deploy'}] |
| 5 | TEST-SN-0005 is checked in | PASS | outcome='checked_in' assignee=None |
| 6 | recipient items are confirmed | PASS | status='passed' detail={'checked_in': ['TEST-SN-0005'], 'kept': []} |
| 7 | device is checked out with Deployed status | PASS | stage='passed' assignee=5 status='Deployed' |
| 8 | case cancelled (cleanup) | PASS |  |
