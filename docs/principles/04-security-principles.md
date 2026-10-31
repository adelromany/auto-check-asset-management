# 04 — Security Principles (RED LINE)

This system runs inside a company and controls who is recorded as holding company equipment. Every line of code must meet this file. When unsure, choose the stricter option.

## Secrets and configuration
- SEC-01 No secret is ever committed: tokens, passwords, client secrets, session secrets, `.env`, database files, uploaded documents, `deploy/snipeit-dev/.env`. Only `.env.example` with empty or fake placeholders.
- SEC-02 All settings are read in `app/config.py` only. If `SSO_ENABLED=true` and `SESSION_SECRET` is empty or `change-me`, the application refuses to start.
- SEC-03 `SSO_ENABLED=false` is a development bypass only. It must log a loud warning and must never be the default in documentation for production.

## Authentication and authorization
- SEC-04 Every new route depends on `current_user`, except the agent submit endpoint and the liveness endpoint. Authorization is enforced server-side in the route/service, never inferred from what the UI hides.
- SEC-05 The engineer identity always comes from the SSO session. A client-supplied name or email is never trusted as an actor.
- SEC-06 The recipient identity reported by the agent is an UNTRUSTED assertion. No Snipe-IT write uses it until an engineer explicitly confirms a Snipe-IT user. The confirmation (who, when) is stored and audited.
- SEC-07 Session cookies: HttpOnly, SameSite=Lax, `Secure` whenever HTTPS is on (`HTTPS_ONLY`).

## Input, output, injection
- SEC-08 Parameterized queries only (SQLAlchemy). Never build SQL from strings.
- SEC-09 All request bodies are validated by pydantic models with explicit types and length limits. Unknown stage names, statuses, and ids return 4xx.
- SEC-10 No `innerHTML` with data, no `eval`, no inline event handlers built from data. Jinja autoescape stays on. Dynamic text goes through `textContent`.
- SEC-11 State-changing session-authenticated routes require a per-session CSRF token header and a matching `Origin` when present.
- SEC-12 Security headers on every response: `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, restrictive `Content-Security-Policy` (self only; no external hosts, no CDN).

## Files
- SEC-13 Uploads: allow only PDF, PNG, JPEG; verify magic bytes; enforce the size limit while streaming; store under a server-generated UUID name; never use the client filename for paths; never serve the storage directory statically; downloads require authentication; record SHA-256.
- SEC-14 Source CSVs or spreadsheets containing credentials must never be imported. Password columns are dropped, not stored.

## External systems
- SEC-15 The Snipe-IT token lives only in server configuration. It is never sent to the browser, never logged, never in exception text.
- SEC-16 Every outbound request has a timeout. Only idempotent GETs are retried. POSTs are never retried automatically.
- SEC-17 No automatic creation of Snipe-IT users or assets. No automatic rollback of Snipe-IT writes; failures are shown and retried by a human.
- SEC-18 Writes are attributed: the engineer's email is written into the Snipe-IT note and events table. Verified v8.8.3 history records the API token owner as actor; with the configured service token that is the service account (D-12, D-62).
- SEC-27 Agent `user_domain` and `console_user` values are untrusted device assertions. Local or empty identities cannot auto-confirm a recipient; confirmation remains an explicit engineer action and self-matches require acknowledgement.

## Data protection
- SEC-19 Agent reports are redacted before storage: the Windows partial product key is never stored. Full payloads are never logged.
- SEC-20 Personal data (names, emails, usernames) is stored only where needed for the workflow. Retention policy is an open decision and is listed in `docs/OPEN_QUESTIONS.md`.
- SEC-21 Employee-activity monitoring (for example logon reporting) requires HR/legal approval and is out of scope.

## Known gaps (tracked, not hidden)
- SEC-22 The agent submit endpoint trusts any holder of a valid short code. Binding a single-use token into the generated script is a future decision (Q-3).
- SEC-23 Transport is plain HTTP until HTTPS is implemented (separate branch). Cookies must not be marked `Secure` until then, and this is documented.

## Hardening added in Phase 8
- SEC-24 `/api/session/{code}/submit` and the recipient search are rate limited by an in-memory sliding window (60 requests per 60 seconds by default). The limiter is single-process; multi-worker deployment needs a shared store (Q-4).
- SEC-25 The CSP is self-only and contains no `unsafe-inline`, `unsafe-eval` or external host. Theme bootstrap, diagnostics and report styles are self-hosted files; do not reintroduce inline script or style.
- SEC-26 The CSRF check is skipped when `SSO_ENABLED=false` because no authenticated session cookie exists in the development bypass. Production runs with SSO on.

## Review checklist (run on every change)
Secrets absent? Route authenticated? Input validated? Output escaped? Upload rules applied? Token kept out of logs? Failure path returns a generic error? Events written?
