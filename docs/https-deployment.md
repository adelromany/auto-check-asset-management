# HTTPS deployment (deferred — not implemented)

Do this only when the company can terminate TLS for the portal. Nothing in
the app changes; tier 1 clipboard starts working by itself.

## Requirements

1. **Internal DNS name** for the portal (e.g. `handover.corp.local`) pointing
   at the host or reverse proxy.
2. **Certificate** for that name from the company's internal CA (or a public
   name + public cert if the portal is ever internet-facing).
3. **Reverse proxy** (nginx / Caddy / IIS ARR) terminating TLS and forwarding
   plain HTTP to uvicorn on localhost.
4. **Run uvicorn behind the proxy with forwarded-proto honored:**
   `uvicorn app.main:app --host 127.0.0.1 --port 8080 --proxy-headers`
   so `request.url.scheme` / `location.origin` seen by the app stay `https`.
5. **Env for production:**
   `HTTPS_ONLY=true` (session cookie gets the `Secure` flag),
   `SSO_ENABLED=true`, real `AZURE_*` values, and `REDIRECT_URI` using the
   `https://` public name (must match the Entra app registration exactly).
6. **Entra app registration:** add the `https://<name>/auth/callback`
   redirect URI (Web platform). `http://` non-localhost URIs are generally
   rejected by Entra — this is why SSO over `http://IP:port` needs attention.

## Verify after cutover

- Open the portal via the https name: `window.isSecureContext === true`.
- `/diag/clipboard` (temporarily `ENABLE_DIAG=true`): Method A succeeds.
- Login flow works end to end; session cookie has `Secure`.
- Then set `ENABLE_DIAG=false` again.
