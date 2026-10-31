# Local Snipe-IT for development

A throwaway Snipe-IT v8 instance (Snipe-IT + MariaDB) used to exercise the
Handover Portal against a real API. **Development only.** Do not reuse this
compose file, its credentials, or its data in production.

## Quick bootstrap (Windows)

From the repository root, run `.\deploy\snipeit-dev\bootstrap.ps1`.
The script creates the ignored development environment file if needed, starts
the stack, initializes Passport/settings/admin/test fixtures, and writes only
`SNIPEIT_URL` and `SNIPEIT_TOKEN` to the root `.env`. It is safe to rerun and
does not print the generated token.

## Login

- URL: <http://localhost:8081>
- Email/username: `admin@example.test` / `admin`
- Password: `ChangeMe-Dev-Only-1`
- These credentials are for the loopback development instance only; never
  reuse them.

To reset the development database and start over, run `docker compose down -v`
from this directory, then rerun the bootstrap from the repository root. This
deletes the local Snipe-IT development data.

## 1. Create the environment file (manual alternative)

```powershell
cd deploy/snipeit-dev
Copy-Item .env.example .env
```

Generate an application key and put it in `.env` as `SNIPEIT_APP_KEY`
(the value must start with `base64:` and decode to 32 bytes):

```powershell
python -c "import base64,os;print('base64:'+base64.b64encode(os.urandom(32)).decode())"
```

Also replace both database passwords in `.env`. Never commit `.env`; the
repository ignores it.

## 2. Start it

```powershell
docker compose up -d
docker compose ps
docker compose logs -f snipeit
```

Wait until the log shows the migrations finished and the web server is
listening, then open <http://localhost:8081>. The portal remains at
<http://localhost:8080>.

## 3. Create the first admin

Either complete the web setup at <http://localhost:8081/setup>, or run the
artisan command non-interactively:

```powershell
docker compose exec snipeit php artisan snipeit:create-admin `
  --first_name=Dev --last_name=Admin `
  --email=admin@example.test --username=admin `
  --password="ChangeMe-Dev-Only-1"
```

Check the command's `--help` first if the options differ in your image
version; the web setup is the fallback.

> Prefer the web setup wizard: it also creates the `settings` row that several
> database-backed flows assume. On an instance created purely from models/CLI,
> bootstrap that row explicitly before trying the API (verified gap in this
> stack's fresh runs on v8.8.3).

### 3b. Generate the OAuth keys and make them readable (required for the API)

The Snipe-IT API uses Passport keys. On v8.8.3 in this image a fresh container
does not have them, and the generated ones are root-only while the web server
runs as `apache`. Both give an HTTP 500 on every API call with a Laravel log
entry `Key path ".../oauth-public.key" does not exist or is not readable`.

```powershell
docker compose exec snipeit php artisan passport:keys --force
docker compose exec snipeit php artisan passport:install --force
docker compose exec snipeit sh -c "chmod 644 /var/lib/snipeit/keys/oauth-*"
```

`passport:install` also creates the personal/password grant clients that
`snipeit:make-api-key` (step 5) requires; without it the key command fails with
"Personal access client not found".

## 4. Create the test user and test asset

In the UI:

1. **Create a user** named `TEST-Recipient` with username `TEST-recipient`
   and email `test.recipient@example.test`.
2. **Create an asset** with serial `TEST-SN-0001`, asset tag `TEST-A-0001`,
   a model and a category, and status **Ready to Deploy**. Leave it
   unassigned.
3. Optionally create a second asset and check it out to the test user, so the
   "recipient's old devices" flow has data.

Every object the live tests touch must start with `TEST-` — this includes the
**username** (`test.recipient` is rejected by their guard; `TEST-recipient`
works) — and the live tests refuse to modify anything else.

## 5. Create an API token

In Snipe-IT: **Admin → API keys → Create New**. Copy the token once. On a
headless instance you can mint one with the admin user's id instead:

```powershell
docker compose exec snipeit php artisan snipeit:make-api-key `
  --user_id=1 --name=dev-portal --key-only
```

## 6. Point the portal at it

In the portal's own `.env` (repository root):

```dotenv
SNIPEIT_URL=http://localhost:8081
SNIPEIT_TOKEN=<the token from step 5>
```

Restart the portal, then check:

```powershell
curl.exe http://localhost:8080/api/snipeit/health
curl.exe "http://localhost:8080/api/snipeit/device?serial=TEST-SN-0001"
```

Both require an authenticated session; sign in first or use the browser.

## 7. Optional: run the live tests

```powershell
$env:SNIPEIT_LIVE_TEST = "1"
$env:SNIPEIT_URL = "http://localhost:8081"
$env:SNIPEIT_TOKEN = "<token>"
python -m pytest tests/test_snipeit_live.py -m live -q
```

The live tests create/clean up only `TEST-` objects and are skipped by
default. They are not part of the normal suite.

Last full run (2026-10-31, v8.8.3-alpine, admin + `TEST-recipient` +
`TEST-SN-0001` seeded): **6 passed**. Snipe-IT rewrites uploaded filenames and
does not return file size in its listing; the client maps the same-client
upload response to its logical original name, while Stage 9 matches the stored
normalized basename suffix across requests. The owner accepted the possible
same-basename collision; see `docs/snipeit-api-verified.md`.

## Reset

```powershell
docker compose down -v
```

## Login

The development-only login is at <http://localhost:8081>: username
`admin` (email `admin@example.test`), password `ChangeMe-Dev-Only-1`.
Use these credentials only on the loopback development instance; never reuse
them. To reset the password and database, run `docker compose down -v`, then
run `./bootstrap.ps1` again.

`-v` deletes both volumes (database and uploads). All development data is
lost, which is the point.
