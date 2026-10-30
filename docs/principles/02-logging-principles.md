# 02 — Logging Principles

- LOG-01 Use Python's standard `logging` only. One configuration function in `app/logging_config.py`; level from `LOG_LEVEL`.
- LOG-02 Format: one line per record, `key=value` pairs, UTC timestamp, level, logger name, `request_id`. Human readable first, machine parsable second.
- LOG-03 Every request gets a `request_id` (generated server-side, returned in `X-Request-ID`). Services receive it through context, not through function parameters sprinkled everywhere.
- LOG-04 Levels: DEBUG developer detail (off in production); INFO business milestones (handover created, stage passed, Snipe-IT write done); WARNING recoverable anomaly (stage blocked, retry used, SSO disabled); ERROR a failed operation that needs attention (Snipe-IT unreachable, verification failed, unhandled exception with stack trace); CRITICAL service cannot continue (cannot start due to missing secret).
- LOG-05 NEVER log: passwords, API tokens, `Authorization` headers, session cookies, Windows partial product keys, full agent payloads, uploaded file contents, full request bodies. Log identifiers (handover id, serial, Snipe-IT ids) instead.
- LOG-06 Two different records exist and must not be confused: (a) technical logs (this file), disposable; (b) the `events` table, the append-only business audit trail — who did what to which handover, when, with outcome. Every state change and every Snipe-IT call writes an event with the acting engineer's email.
- LOG-07 `events` are insert-only. No update or delete method exists in its repository; a test proves it.
- LOG-08 Errors returned to clients are generic and carry the `request_id`; stack traces go to the log only.
- LOG-09 External calls log: target system, operation, duration, outcome status. Never the token. A test captures logs and asserts the token string is absent.
- LOG-10 Startup logs the effective non-secret configuration summary (database dialect, SSO on/off, Snipe-IT host) and a loud WARNING if `SSO_ENABLED=false`.
