# Phase 01: Snipe-IT integration (GATE). Prove the real calls first.

Goal: every Snipe-IT call that V2 needs works against a REAL Snipe-IT, and the app's client exposes company, model, category and status. Nothing after this phase is trusted until this phase passes.

Before you start: read `00-README` sections A and B. Put the V2 files in the repo: `mkdir -p docs/v2 docs/ui` and copy `00` to `08` into `docs/v2/`, and `reference-demo.html` into `docs/ui/reference-demo.html` (the owner provides them; if missing, ask).

## Step 1.1 Start Snipe-IT dev
Read only the top of `deploy/snipeit-dev/README.md` (`sed -n 1,70p`). Start the stack with its documented commands (port 8081; the portal uses 8080). Docker Hub is reachable. If a pull or install fails, show the exact error, retry once, then STOP and ask the owner for the exact permission. Never disable TLS verification.
Check: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/login` prints `200`.

## Step 1.2 Token and `.env`
Create the API token (README path or artisan). Put `SNIPEIT_URL=http://localhost:8081` and `SNIPEIT_TOKEN=<token>` in `.env` (git-ignored; confirm with `git check-ignore .env`). NEVER print the token in logs, commits or reports.
Check: `curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8081/api/v1/users/me | head -c 200` returns JSON with the admin user (do not paste the token in HANDOFF).

## Step 1.3 Seed test data (idempotent script)
Create `tools/snipeit_seed.py` (standard `httpx`, reads `SNIPEIT_URL` and `SNIPEIT_TOKEN` from the environment, TEST data only, safe to run twice). It creates if missing:
- companies `B.tech`, `Nexta`, `Mylo` (`POST /api/v1/companies`)
- status label `Maintenance` (type `undeployable`); `Ready to deploy` already exists, only verify it
- category `Laptop`, manufacturer `Dell`, one model `Latitude 5440`
- 5 assets (`POST /api/v1/hardware`) with serials `TEST-SN-0001` to `TEST-SN-0005`: 0001 B.tech and 0002 B.tech (Ready to deploy), 0003 Mylo (Ready to deploy), 0004 Nexta (Ready to deploy), 0005 B.tech (Ready to deploy)
- 4 users (`POST /api/v1/users`): `test.btech1` (B.tech), `test.btech2` (B.tech, who also gets asset 0005 checked out), `test.mylo1` (Mylo), `test.nexta1` (Nexta)
Print one line per object: `created` or `exists`. Handle 422 "already exists" as `exists`.
Check: run it twice; the second run prints only `exists`.

## Step 1.4 Extend the client DTOs (unit-tested)
In `app/clients/snipeit.py` add to `SnipeItAsset`: `company_id: int | None`, `company: str | None`, `status_id: int | None`. Add to `SnipeItUser`: `company_id`, `company`. Fill them in `_asset_from_json` and `_user_from_json` from the nested `company` object (use `_nested_name` and `_int_or_none`). Add method `async def find_status_label_id(self, name: str) -> int | None` (case-insensitive over `list_status_labels`).
Add unit tests in `tests/test_snipeit_client.py` with a fake JSON that has `company: {id: 3, name: "B.tech"}` and one without a company.
Check: `pytest tests/test_snipeit_client.py -q` green.

## Step 1.5 Probe script against the REAL instance
Create `tools/snipeit_probe.py`. It uses the app's own `SnipeItClient` (not raw httpx) and runs these checks in order, printing `PASS` or `FAIL <reason>` for each, and writes a table to `docs/snipeit-integration-report.md` (no tokens, no secrets; short response excerpts only):
1. `whoami`
2. `get_asset_by_serial("TEST-SN-0001")` returns `company == "B.tech"`, `model`, `category`, `status`
3. `list_status_labels` contains `Ready to deploy` and `Maintenance`
4. `update_asset_status` TEST-SN-0001 to `Maintenance`, re-read shows `Maintenance`, then back to `Ready to deploy`
5. `search_users("test.btech")` returns users WITH `company`
6. `list_user_assets` of `test.btech2` includes TEST-SN-0005
7. `checkin_asset` TEST-SN-0005 then verify it has no assignee
8. `checkout_asset_to_user` TEST-SN-0001 to `test.btech1`, verify `assigned_to` is that user and the status is Deployed
9. `upload_asset_file` a small PNG to TEST-SN-0001, then `list_asset_files` contains the same filename
10. `checkin_asset` TEST-SN-0001 (cleanup) and set status back to `Ready to deploy`
11. Error shapes: `get_asset_by_serial("NOPE-999")` raises the client's not-found error; a bad token gives the auth error (use a throw-away client with a wrong token)
Every step cleans up after itself so the script can be re-run.
Check: `python tools/snipeit_probe.py` prints 11 PASS lines. If any FAIL: fix the client (or report an environment problem) and re-run. If `company` is missing from the API response, STOP and tell the owner (the design then needs a fallback).

## Step 1.6 Live tests in pytest
In `tests/test_snipeit_live.py` (skipped unless `SNIPEIT_LIVE=1`) add one test per probe check 2, 4, 5, 8 (short). Use the `TEST-` data only.
Check: `SNIPEIT_LIVE=1 pytest tests/test_snipeit_live.py -q` green; without the variable they are skipped.

## Step 1.7 Close the phase
Add to `docs/snipeit-api-verified.md` a short section "V2 additions" pointing to `docs/snipeit-integration-report.md`. Update `HANDOFF-V2.md` with: `PHASE 01 DONE`, the number of PASS lines, and anything unexpected. Commit.

Done when: 11 PASS lines, unit tests green, report committed, no secret in the diff (`git diff origin/fix/ui-recovery --stat` and grep for the token prefix).
Next file: `02-handover-catalog-and-device.md`.
