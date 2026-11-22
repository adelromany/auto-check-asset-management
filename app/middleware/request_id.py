"""Server-generated request ids for logs and response correlation."""

from __future__ import annotations

import secrets
import logging

from starlette.requests import Request

from app.request_context import request_id_var

logger = logging.getLogger(__name__)


class RequestIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = secrets.token_hex(8)
        token = request_id_var.set(request_id)

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            # Delegate to the app's error rendering (HTML for browsers, JSON
            # for APIs) so 500s look like every other error; this middleware
            # only adds the id header and the server-side traceback log.
            logger.exception(
                "unhandled_request_error exception_type=%s", type(exc).__name__
            )
            from app.main import _internal_error

            request = Request(scope, receive=receive)
            response = await _internal_error(request, exc)
            await response(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
