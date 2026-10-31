# Snipe-IT API shapes — verification status

**Status: BLOCKED.** No real Snipe-IT instance has been reached from this
environment yet, so this file intentionally contains **no claimed response
shapes**. Everything the client does today is exercised only against
`tests/fakes/snipeit_fake.py`; the fake is not evidence of real API behavior.

## Why it is blocked

Docker is installed and the daemon is running:

```
Docker version 29.7.2
Docker Compose version v5.5.1
```

`docker compose up -d` in `deploy/snipeit-dev` failed while pulling images
from Docker Hub. Two attempts failed at different network steps:

```
failed to authorize: failed to fetch anonymous token:
Get "https://auth.docker.io/token?...": net/http: TLS handshake timeout
```

```
failed to copy: httpReadSeeker: failed open:
Get "https://registry-1.docker.io/v2/library/mariadb/manifests/sha256:...":
net/http: timeout awaiting response headers
```

The environment's outbound network is slow and unstable (the same limitation
blocked `pytest-cov` and `asyncpg`). This is an infrastructure limit, not a
compose-file defect.

## What the owner must do

Follow `deploy/snipeit-dev/README.md` on a machine with working Docker Hub
access:

1. `Copy-Item .env.example .env`, generate `SNIPEIT_APP_KEY`, set the two DB
   passwords.
2. `docker compose up -d`.
3. Create the first admin (web setup or `php artisan snipeit:create-admin`).
4. Create user `TEST-Recipient` (`test.recipient`) and asset serial
   `TEST-SN-0001`; optionally check a second `TEST-` asset out to that user.
5. Create an API token under **Admin → API keys**.
6. Put `SNIPEIT_URL` / `SNIPEIT_TOKEN` in the portal `.env`.
7. Run `SNIPEIT_LIVE_TEST=1 python -m pytest tests/test_snipeit_live.py -m live -q`.

## What must be recorded here afterwards

For each endpoint, record method, path, request payload, the response fields
the client actually reads, and the Snipe-IT version. Pay special attention to
these, which the fake currently guesses:

| # | Endpoint | Question to answer against the real instance |
|---|----------|----------------------------------------------|
| 1 | `GET /api/v1/users?search=` | Does `rows` contain `id`, `username`, `name`, `email`? |
| 2 | `GET /api/v1/users/{id}` | Is the user wrapped in a single object or in `rows`? |
| 3 | `GET /api/v1/hardware?assigned_to=` | Does the filter accept a numeric user id? |
| 4 | `GET /api/v1/hardware?search=` | Is serial search exact or substring? |
| 5 | `GET /api/v1/hardware/{id}` | How is `assigned_to` shaped when unassigned? |
| 6 | `POST /api/v1/hardware/{id}/checkout` | Are `assigned_to`, `checkout_to_type`, `note` the right fields? |
| 7 | `POST /api/v1/hardware/{id}/checkin` | Is `note` accepted? |
| 8 | `POST /api/v1/hardware/{id}/files` | Multipart field name, extra fields, response shape. |
| 9 | `GET /api/v1/hardware/{id}/files` | `rows` fields: `id`, `filename`, `size`? |
| 10 | `GET /api/v1/users/me` | Is the current user returned directly or in `rows`? |

If real behavior differs from the fake, fix **both** the fake and the client
in the same change. Never adjust only one.

## Version

Not recorded — no instance was reached.
