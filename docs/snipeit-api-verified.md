# Snipe-IT API shapes — verification status

**Status: VERIFIED.** All shapes below were captured live on 2026-10-31 against
Snipe-IT v8.8.3 (image `snipe/snipe-it:v8.8.3-alpine` + MariaDB 11.4, see
`deploy/snipeit-dev/`) with curl and `tests/test_snipeit_live.py`
(`SNIPEIT_LIVE_TEST=1`, token read from a temp file, never printed or committed).
Every value shown is a real response field; values that were `null` are noted as
such. Where the implementation the fake implies differs from the real API, the
difference is listed under "Real vs fake" and fixed together in the client and
the fake on branch `fix/snipeit-live-verification`.

Live-test result: **5 passed, 1 failed** — the single failure
(`test_upload_and_list_test_asset_file`) is a Snipe-IT product limitation, not a
client bug; see "File upload" below.

## Common envelope

List endpoints return a paginated envelope (real keys):

```json
{
  "total": 4,
  "rows": [ { }, { } ],
  "current_page": 1, "per_page": 500, "total_pages": 1,
  "prev_page_url": null, "next_page_url": null
}
```

`limit=N` is honored. Write endpoints (checkout / checkin / upload) return:

```json
{ "status": "success" | "error", "messages": "<string>" | { "<field>": "<msg>" }, "payload": null | { } }
```

On validation error, `status` stays `"error"`, HTTP is 200 or 422 depending on
the endpoint, and `messages` is an **object keyed by field name** (see below),
never a plain string. The client's `_action_result` collapses `messages` via
`str()`, which produces an ugly dict string — acceptable, tests assert on status
only.

## whoami — GET /api/v1/users/me

HTTP 200. Real fields (selected): `id`, `name`, `first_name`, `last_name`,
`display_name` (null unless set), `username`, `email`, `role`
(`"superadmin"`), `permissions` (object with `admin`, `superuser`, `reports.view`,
`licenses.keys` …), `activated` (`true`), `two_factor_optin`, `company`,
` companies` (array), `created_at`/`updated_at`
(`{"datetime": "...", "formatted": "..." }`), `available_actions`,
`assets_count`, `licenses_count`.

Note: the display name is `name`, and `display_name` is a **separate, usually
null field**. When `display_name` is set, the users list API still returns the
computed `name` (`first_name + " " + last_name`), not `display_name`.

## Users

- `GET /api/v1/users?search=<needle>&limit=10` — `rows` of user objects with
  `id`, `username`, `name`, `first_name`, `last_name`, `display_name`, `email`,
  `activated`. Search is case-insensitive and matches username/name/email.
  `total` reflects the matched count.
- Every `TEST-` seeded user was renamed so **username and name both start with
  `TEST-`** (`TEST-user1`, `TEST-user2`, `TEST-recipient`); the original prompts
  used lowercase `test.*` usernames which the live tests' TEST- prefix guard
  rejects. Email stays `test.*@example.test` so searches still find them.

## Assets

`GET /api/v1/hardware/{id}` (single) — HTTP 200, real flattened object
(selected): `id`, `name`, `asset_tag`, `serial`, `model: {id, name}`,
`model_number`, `status_label: {id, name, status_type, status_meta, tag_color}`,
`status` (same shape, duplicate of status_label), `category: {id, name}`,
`manufacturer: {id, name}`, `assigned_to`, `warranty_months`,
`purchase_date` (null or object with `datetime`/`formatted`),
`last_checkout` (object `datetime`/`formatted`),
`last_checkin` (same shape), `checkout_counter`, `checkin_counter`,
`available_actions`, `custom_fields` (`{}` in an instance without fieldsets).

`status_label.status_meta` is `"deployable"` when unassigned and flips to
`"deployed"` while assigned; the client does not depend on it (it reads
`assigned_to`), but fake and tests should not assert a single value.

`assigned_to` is:
- `null` when unassigned (both in the single view and in list rows);
- when assigned, an object: `{"id": 4, "username": "TEST-recipient",
  "name": "TEST-Recipient", "first_name": "TEST-", "last_name": "Recipient",
  "email": "test.recipient@example.test", "employee_number": null,
  "jobtitle": null, "type": "user"}`.

The client maps this with `_int_or_none(assigned_to["id"])` → correct.

### Difference: list filtering

- `GET /api/v1/hardware?search=<needle>&limit=10` **works** (case-insensitive
  substring over serial/tag/name). Confirmed with `search=TESTSERIAL`
  → `total=3`.
- `GET /api/v1/hardware?assigned_to=<id>` alone is **ignored** — with one
  seeded assigned asset and four total, it returned all four (`total=4`).
- `GET /api/v1/hardware?assigned_to=<id>&assigned_type=App%5CModels%5CUser`
  (URL-encoded `App\Models\User`) **correctly filters** (`total=2`, ids 1–2 for
  user 2). The `assigned_type` value must be the full PHP class name, not
  `"user"`.
- `GET /api/v1/users/{id}/assets` also lists that user's assets, but in v8.8.3
  its rows have `assigned_to: null` even for assigned assets (checked with
  `GET /api/v1/users/2/assets` → rows ids 1, 2 both `assigned_to: null`).
  The portal does not use this endpoint; `list_user_assets` uses the
  `hardware?assigned_to&assigned_type` filter, which is now fixed in the client.

Client fix (paired in `tests/fakes/snipeit_fake.py`): `list_user_assets` sends
`assigned_to=<id>` **and** `assigned_type="App\Models\User"`. The fake mirrors
the "ignored without assigned_type" behavior.

## Checkout — POST /api/v1/hardware/{id}/checkout

Payload that works (verified twice, HTTP 200):

```json
{
  "checkout_to_type": "user",
  "assigned_user": 4,
  "note": "TEST- live checkout"
}
```

Response:

```json
{"status": "success", "messages": "Asset checked out successfully.",
 "payload": {"asset": "TEST-A-0001"}}
```

(`payload.asset` contains the asset tag, not the id.)

### Difference: field name

Sending `{"checkout_to_type": "user", "assigned_to": 4, ...}` — the field name
the client used before this branch — is **rejected** by v8.8.3 with:

```json
{"status": "error", "messages": {
   "assigned_user": ["The assigned user field is required when none of
      assigned asset / assigned location are present."],
   "assigned_asset": ["..."], "assigned_location": ["..."], }, "payload": null}
```

Client fix: `checkout_asset_to_user` sends `assigned_user`. Fake updated to
read `assigned_user` (with a tolerance for `assigned_to` so old fake callers
keep working).

## Checkin — POST /api/v1/hardware/{id}/checkin

Payload `{"note": "..."}` works. Response (HTTP 200):

```json
{"status": "success", "messages": "Asset checked in successfully.",
 "payload": {"asset_tag": "TEST-A-0001", "model": "ThinkPad T14",
             "model_number": "T14"}}
```

After checkin, `GET /api/v1/hardware/{id}` shows `assigned_to: null`,
`status_label.status_meta` back to `"deployable"`, and `checkin_counter`
incremented. The live round-trip test passes with this endpoint unchanged.

## File upload — POST /api/v1/hardware/{id}/files

The multipart field name must be **`file[]`** (a plain `file` field is not
accepted). Verified with curl:

```
curl -X POST -H "Authorization: Bearer $TOKEN" ...
  -F "file[]=@TEST-live-upload.pdf;type=application/pdf" -F "note=TEST- live test"
  http://localhost:8080/api/v1/hardware/4/files
```

Response (HTTP 200, payload is a one-row page):

```json
{"status": "success", "messages": "File successfully uploaded ",
 "payload": {"total": 1, "rows": [{"id": 14, "icon": "far fa-file-pdf",
   "name": "asset-4-nCxy0vyD-test-live-upload.pdf", "item": {"id": 4,
   "type": "assets"}, "filename": "asset-4-nCxy0vyD-test-live-upload.pdf",
   "filetype": "pdf", "mediatype": "pdf",
   "url": "http://localhost:8080/assets/4/files/14", "note": null,
   "created_by": {"id": 1, "name": "Dev Admin"}, "deleted_at": null,
   "inlineable": true, "exists_on_disk": true, "available_actions":
   {"delete": true}}], ...}}
```

Client fix: `upload_asset_file` uses `files={"file[]": ...}`. Fake updated to
read the `file[]` part.

### Verified Snipe-IT limitation (not fixable in the client)

`app/Http/Requests/UploadFileRequest.php` (v8.8.3, line 80) always rewrites the
stored filename to `{item_id}-{random8}-{slug(original basename)}.{ext}` —
lowercased and never preserving the original name. `GET /api/v1/hardware/{id}/files`
returns only the stored name (`filename` === `name` === stored). Therefore:

- the stored record **never** equals the uploaded filename;
- `note` sent with the upload is **not** persisted on the row (listing shows
  `note: null` even though the upload accepted it).

Consequence, recorded honestly: live test
`test_upload_and_list_test_asset_file` passes its upload step (HTTP 200,
`status: "success"`) and fails only on
`assert any(item.filename == filename for item in files)` — the original
`TEST-live-upload.pdf` can never reappear in the listing. Fixing that would
require editing the existing test (forbidden). The fake keeps returning the
original filename; the divergence is intentional and documented here.

D-40's "matched by sanitized name and byte size" check therefore must match on
the sanitized name it searches for. **Action for the owner:** stage 9's
idempotent re-check should treat "file with same byte size and same lowercased
basename inside the stored name" as already-present, or D-40 stays satisfied
because the portal only uploads when its own sanitized search fails — the
second upload will still succeed but create a duplicate. UNVERIFIED against a
long-running instance whether duplicates cause any error; the live run did not
test duplicate uploads.

## Attribution (D-12) — action_logs behind the API

Checkout/checkin executed via the API with a **personal admin token** of user 1
were recorded by v8.8.3 as:

```
action_logs row: item_type=App\Models\Asset#4, target_type=App\Models\User#4,
action_type=checkout, created_by=1, action_source=api
```

- `created_by` = **the token owner (user 1)**, not the recipient and not null.
- `action_source` = `"api"` distinguishes API writes from UI (`"cli/unknown"`
  appeared for seeded CLI updates).
- The note passed with the checkout is stored in `note` (visible in the log).

So D-12 is now answered with evidence: **attribution follows the API token
owner**. With the service-account token, history shows the service account as
actor — exactly the interim limitation D-12 documented. The engineer email in
the note ("engineer@example.test via Handover Portal ...") is what makes the
history auditable beyond the token owner. D-12 can be marked verified; changing
the mechanism to per-engineer personal tokens remains an owner decision.

## Bootstrap gotchas (fresh instance)

Documented in `deploy/snipeit-dev/README.md`:

1. `passport:keys`/`passport:install` must run and the generated
   `/var/lib/snipeit/keys/oauth-*.key` files must be made **readable by the
   web-server user** (`apache` in this image): `chmod 644 …`. Otherwise every
   API call fails with HTTP 500 and Laravel log
   `Key path ".../oauth-public.key" does not exist or is not readable`
   (the root CLI can read them even though the API cannot).
2. `snipeit:make-api-key --user_id=<admin id> --name=<name> --key-only`
   creates the personal access token used for live tests; it fails with
   "Personal access client not found" until `passport:install --force` ran.
3. The instance's `settings` table must have its config row (created by the web
   setup wizard); seeded-through-model setups must create it explicitly
   (`Setting::create` style), because several API endpoints return 500 without
   it. UNVERIFIED exactly which endpoints require the row in v8.8.3 — our
   instance had it from the wizard.
