# Snipe-IT integration report

Live instance: `deploy/snipeit-dev` (Snipe-IT v8), local only.
Probe: `python tools/snipeit_probe.py` (uses `app/clients/snipeit.py`).
No tokens or secrets are recorded here.

## Polish verification — 2026-11-28

Environment unavailable: `tools/snipeit_seed.py` and `tools/snipeit_probe.py` both failed with `WinError 10061` connecting to the configured local instance. These are environmental failures, not passing integration evidence. No live-scenario claim is made; the last successful baseline is retained below in version history. Restart the development Snipe-IT instance and rerun both commands before deployment.

## Latest probe (all checks blocked by connection refused)

| # | Check | Result | Detail |
|---|---|---|---|
| 1 | whoami | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 2 | asset by serial has company/model/category/status | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 3 | status labels include Ready to deploy and Maintenance | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 4 | update asset status and restore | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 5 | search_users returns company | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 6 | list_user_assets includes TEST-SN-0005 | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 7 | checkin TEST-SN-0005 clears assignee | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 8 | checkout TEST-SN-0001 to test.btech1 | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 9 | upload file and list it | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 10 | cleanup checkin and Ready to deploy | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
| 11 | error shapes (not found, bad token) | FAIL | SnipeItUnavailable: Could not reach Snipe-IT. |
