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
| 9 | upload file and list it | PASS | probe-19680.png listed (10 files) |
| 10 | cleanup checkin and Ready to deploy | PASS | checked in, Ready to deploy |
| 11 | error shapes (not found, bad token) | PASS | SnipeItNotFound + SnipeItAuthError |
