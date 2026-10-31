# 02 — Logging Principles

Status: both the **business audit trail** and the **structured technical
logging/request-id path** are implemented. The limits on personal data and
secrets remain mandatory.

## Business audit trail (implemented)

- LOG-01 The `events` table is the append-only audit trail: who did what to
  which handover, when, with outcome. Every state change and every Snipe-IT
  call writes an event.
- LOG-02 `app/repositories/events.py` exposes insert and read only. No update
  or delete method exists; `tests/test_persistence.py` proves it.
- LOG-03 Event payloads carry identifiers (handover id, serial, Snipe-IT ids,
  HTTP status) and never file bytes, tokens, cookies or full agent payloads.
- LOG-04 Snipe-IT write events include the operation outcome and the Snipe-IT
  HTTP status when available. The engineer's email is stored with the event
  and in the Snipe-IT note.
- LOG-05 The Windows `partial_key` is removed before storage; full payloads
  are never logged.

## Technical logging (implemented)

- LOG-06 `app/logging_config.py` configures one structured key/value handler
  with UTC timestamps and the configured log level.
- LOG-07 `RequestIdMiddleware` creates a server-side request id, returns it in
  `X-Request-ID`, and adds it to log records. Unexpected errors return a
  generic response with that id; logs contain the exception class only, never
  exception text or stack traces that may include personal data.
- LOG-08 Startup records the effective database dialect, SSO state and Snipe-IT
  host. The development SSO bypass is a warning.
- LOG-09 Snipe-IT calls log operation category, target host, status and elapsed
  time. URL paths, tokens, identities, and request bodies are excluded.
- LOG-13 Third-party HTTP and server-access loggers do not record full URLs or
  query strings, which can contain names, usernames, or email filters.

## Rules that still apply to any new code

- LOG-10 NEVER log or store: passwords, API tokens, `Authorization` headers,
  session cookies, Windows partial product keys, full agent payloads, uploaded
  file contents, or full request bodies. Log identifiers instead.
- LOG-11 Errors returned to clients stay generic. Do not log exception text or
  stack traces that may carry personal data; log only a safe error category.
- LOG-12 A test must continue to assert that the Snipe-IT token never appears
  in exception text or captured logs (`tests/test_snipeit_client.py`).
