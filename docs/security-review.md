# Security Review — Handover Portal

Date: 2026-10-31
Scope: the whole application as built through the 2026-10-31 gap-fix run,
checked against `docs/principles/04-security-principles.md` (SEC-01 … SEC-27).

Verdict: **PASS with tracked gaps**. No unresolved secret, injection or
authorization defect was found. The gaps below are documented decisions, not
silent exceptions.

## Changes made in Phase 8

1. **Fail-closed startup** (`app/security/startup.py`, called by
   `app/main.py:create_app`). If `SSO_ENABLED=true` and `SESSION_SECRET` is
   empty, whitespace, `change-me` or any case variant of it, the application
   raises `RuntimeError` and does not start. Tests set an explicit secret.
2. **CSRF + Origin** (`app/security/csrf.py`). Every `POST`/`PUT`/`PATCH`/
   `DELETE` under `/api/handovers` or `/api/dashboard` must send
   `X-CSRF-Token`, compared with `secrets.compare_digest` against the token in
   the signed session. If an `Origin` header is present it must match the
   request host or `APP_HOST`. The agent endpoint
   `/api/session/{code}/submit` is outside the protected prefixes because it
   authenticates with a short code, not a cookie. With `SSO_ENABLED=false`
   there is no authenticated cookie to protect, so the check is skipped; that
   bypass is logged as a warning by `app/main.py` during startup.
3. **Token delivery** (`GET /api/me`). The token is returned in the
   `X-CSRF-Token` response header; the JSON body is unchanged, so the
   characterization contract stays intact. `static/js/shell.js` caches it and
   the two page modules send it on writes.
4. **Security headers** (`app/security/headers.py`). Every response carries
   `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
   `X-Frame-Options: DENY` and a self-only CSP
   (`default-src 'self'; script-src 'self'; style-src 'self'; …`;
   `frame-ancestors 'none'`; no `unsafe-inline`, no external host).
5. **CSP cleanup.** The external Google Fonts links were removed from
   `templates/index.html` and `templates/diag_clipboard.html` (system fonts are
   used), the inline theme scripts were replaced by
   `static/js/theme-init.js`, the clipboard diagnostic script moved to
   `static/js/diag_clipboard.js`, and the printable report style moved to
   `static/css/report.css`. No policy was weakened to keep an inline script.
6. **Rate limiting** (`app/security/ratelimit.py`). A dependency-free sliding
   window limits the agent submit endpoint and recipient search per client
   address. Defaults: 60 requests / 60 seconds each, configurable with
   `RATE_LIMIT_*`. It is **single-process only**; see Q-4.
7. **Secrets scan** (`tests/test_security_hardening.py`). The test reads every
   tracked file and fails on a non-placeholder `SNIPEIT_TOKEN`,
   `AZURE_CLIENT_SECRET`, `SESSION_SECRET`, or a private-key header.

## Checklist against principle 04

| Rule | Result | Evidence |
|---|---|---|
| SEC-01 no committed secrets | PASS | `.env` and `deploy/snipeit-dev/.env` are ignored; `.env.example` values are empty/`CHANGE_ME`; secrets scan test. |
| SEC-02 fail closed on placeholder session secret | PASS | `app/security/startup.py`; startup tests. |
| SEC-03 dev bypass warns loudly | PASS | `app/main.py` logs a warning when `SSO_ENABLED=false`; not documented as production. |
| SEC-04 every route authenticated except agent submit and liveness | PASS | `current_user` on handover, document, dashboard, Snipe-IT and `/api/me`; `/api/health` and agent submit are the only public routes; page routes redirect to `/login`. |
| SEC-05 engineer identity from SSO | PASS | `current_user` reads only the session; no client-supplied actor is trusted. |
| SEC-06 recipient assertion is untrusted until confirmed | PASS | Phase 5 recipient confirm stores who/when; writes require a confirmed Snipe-IT user. |
| SEC-07 cookie flags | PASS | `HttpOnly` by `SessionMiddleware`, `SameSite=Lax`, `Secure` follows `HTTPS_ONLY`. |
| SEC-08 parameterized SQL | PASS | SQLAlchemy Core/ORM only; no string-built SQL. |
| SEC-09 validated bodies and ids | PASS | Pydantic DTOs with bounds; invalid stage/status/uuid return 4xx. |
| SEC-10 no data in `innerHTML` / autoescape on | PASS | Jinja autoescape; page JS uses `textContent`; the only `innerHTML` is a constant SVG path map in `static/app.js` and an empty-string clear in the diagnostic. |
| SEC-11 CSRF + Origin | PASS | `CsrfMiddleware`; tests cover missing/wrong token, foreign/same Origin and the agent exclusion. |
| SEC-12 security headers | PASS | `SecurityHeadersMiddleware`; tests assert all four headers and the self-only policy. |
| SEC-13 upload rules | PASS | Magic bytes, streaming size limit, UUID names, SHA-256, authenticated download, storage directory not mounted. |
| SEC-14 no credential spreadsheets | PASS | No CSV/spreadsheet import exists. |
| SEC-15 token never leaves server | PASS | Token only in `app/clients/snipeit.py`; never logged or put in exception text; tests assert absence. |
| SEC-16 timeouts and GET-only retries | PASS | Client timeout; two GET retries; POST never retried. |
| SEC-17 no automatic user/asset creation or rollback | PASS | Phase 5/6 only assign/upload existing records and report failures. |
| SEC-18 attribution in note and events | PASS | Engineer email + portal marker + case id in the checkout note and event trail. Live v8.8.3 history records the API token owner as actor; the service-token limitation is verified in D-12/D-62. |
| SEC-19 redaction before storage | PASS | `windows_activation.partial_key` stripped; payloads never logged. |
| SEC-20 data minimisation / retention | PASS (retention OPEN) | Only workflow fields stored; retention is tracked in D-14. |
| SEC-21 no employee monitoring | PASS | No logon reporting or activity monitoring implemented. |
| SEC-22 agent code binding | **OPEN** | Still any holder of a valid short code; tracked as Q-3. |
| SEC-23 plaintext HTTP until HTTPS | **KNOWN** | Cookies are not `Secure` when `HTTPS_ONLY=false`; deployment guide records the constraint. |
| SEC-24 agent recipient assertion handling | PASS | Domain/console identity values are treated as untrusted; local/empty identities cannot be auto-confirmed, and matching engineer identity needs explicit acknowledgement. |
| SEC-25 log secrecy | PASS | Structured logs omit paths, request bodies, tokens, and identities; token non-disclosure test passes. |
| SEC-26 request correlation | PASS | Server-generated request ID is returned in `X-Request-ID`; generic 500 responses include the same id; logs contain exception classes only, and HTTP/access loggers cannot leak query strings. |
| SEC-27 age-based stalling | PROPOSED | SQL-based inactivity status is configurable, but the 24-hour business threshold remains owner-open (Q-10); it does not expand authorization. |

## Verification run

```
python -m pytest tests/test_security_hardening.py -q
17 passed, 2 warnings

python -m pytest tests -q --ignore=tests/test_clipboard_playwright.py --cov=app --cov-report=term-missing
345 passed, 6 skipped; 93% app coverage
```

The six skipped tests are opt-in live Snipe-IT tests; they were run separately
and all six passed. Browser tests also ran separately: 23 passed, 2 skipped,
2 xfailed. The PostgreSQL migration test passed against a real PostgreSQL 16
container.

## Tracked gaps

- **Agent short code is a bearer secret** (Q-3): anyone who observes it can
  submit a report for that session. Single-use token binding is a future
  decision.
- **Rate limiter is per process** (Q-4): multiple workers each keep their own
  counters. A shared store (Redis or the database) is required before scaling
  out.
- **Snipe-IT attribution** (D-12): the service account appears as actor in
  Snipe-IT history; the engineer is recorded in the note and event trail.
- **Policy choices**: 24 hours remains a proposed stall threshold (Q-10), and
  Office 365 equivalence is unspecified (Q-11).
- **Transport**: plain HTTP is still the default in the development setup;
  cookies become `Secure` only with `HTTPS_ONLY=true`.
