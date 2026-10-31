"""Security headers for every response (SEC-12).

The policy is self-only: no CDN, no external font host, no inline script and
no inline style. The UI was moved to external files so this stays strict.
"""

from __future__ import annotations

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "base-uri 'self'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
    ]
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
}


class SecurityHeadersMiddleware:
    """Attach the fixed security headers to every HTTP response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                for name, value in SECURITY_HEADERS.items():
                    if name.lower().encode("latin-1") not in present:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
