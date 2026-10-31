# 02 — Logging Principles

Status: the **business audit trail is implemented**; structured technical
logging is **not** implemented. This file states the difference instead of
claiming a logging stack that does not exist. See Q-5 in
`docs/OPEN_QUESTIONS.md`.

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

## Technical logging (not implemented)

The following rules remain the target, but no code currently satisfies them.
They must not be reported as done:

- LOG-06 **Structured logging configuration**: there is no
  `app/logging_config.py`; the app uses uvicorn's default logging. A
  `LOG_LEVEL` setting exists in `app/config.py` but is not wired to a
  formatter.
- LOG-07 **Request id**: no middleware generates a request id, returns
  `X-Request-ID`, or puts it in a log context. Error responses are generic but
  do not carry a request id.
- LOG-08 **Level policy and startup summary**: the only startup message is the
  loud `SSO_ENABLED=false` warning printed by `app/config.py`. The effective
  database dialect and Snipe-IT host are not logged.
- LOG-09 **External-call timing**: Snipe-IT calls are not logged with
  duration. Their outcome is recorded in the `events` table instead.

## Rules that still apply to any new code

- LOG-10 NEVER log or store: passwords, API tokens, `Authorization` headers,
  session cookies, Windows partial product keys, full agent payloads, uploaded
  file contents, or full request bodies. Log identifiers instead.
- LOG-11 Errors returned to clients stay generic; stack traces, when they are
  added, must go to the log only.
- LOG-12 A test must continue to assert that the Snipe-IT token never appears
  in exception text or captured logs (`tests/test_snipeit_client.py`).
