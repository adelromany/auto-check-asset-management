# Local Snipe-IT for development

A throwaway Snipe-IT v8 instance (Snipe-IT + MariaDB) used to exercise the
Handover Portal against a real API. **Development only.** Do not reuse this
compose file, its credentials, or its data in production.

## 1. Create the environment file

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
listening, then open <http://localhost:8080>.

## 3. Create the first admin

Either complete the web setup at <http://localhost:8080/setup>, or run the
artisan command non-interactively:

```powershell
docker compose exec snipeit php artisan snipeit:create-admin `
  --first_name=Dev --last_name=Admin `
  --email=admin@example.test --username=admin `
  --password="ChangeMe-Dev-Only-1"
```

Check the command's `--help` first if the options differ in your image
version; the web setup is the fallback.

## 4. Create the test user and test asset

In the UI:

1. **Create a user** named `TEST-Recipient` with username `test.recipient`
   and email `test.recipient@example.test`.
2. **Create an asset** with serial `TEST-SN-0001`, asset tag `TEST-A-0001`,
   a model and a category, and status **Ready to Deploy**. Leave it
   unassigned.
3. Optionally create a second asset and check it out to the test user, so the
   "recipient's old devices" flow has data.

Every object the live tests touch must start with `TEST-`; the live tests
refuse to modify anything else.

## 5. Create an API token

In Snipe-IT: **Admin → API keys → Create New**. Copy the token once.

## 6. Point the portal at it

In the portal's own `.env` (repository root):

```dotenv
SNIPEIT_URL=http://localhost:8080
SNIPEIT_TOKEN=<the token from step 5>
```

Restart the portal, then check:

```powershell
curl.exe http://localhost:8000/api/snipeit/health
curl.exe "http://localhost:8000/api/snipeit/device?serial=TEST-SN-0001"
```

Both require an authenticated session; sign in first or use the browser.

## 7. Optional: run the live tests

```powershell
$env:SNIPEIT_LIVE_TEST = "1"
$env:SNIPEIT_URL = "http://localhost:8080"
$env:SNIPEIT_TOKEN = "<token>"
python -m pytest tests/test_snipeit_live.py -m live -q
```

The live tests create/clean up only `TEST-` objects and are skipped by
default. They are not part of the normal suite.

## Reset

```powershell
docker compose down -v
```

`-v` deletes both volumes (database and uploads). All development data is
lost, which is the point.
