"""Server-generated request ids for logs and response correlation."""

from __future__ import annotations

import secrets
import logging

from starlette.responses import JSONResponse

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
            logger.error(
                "unhandled_request_error exception_type=%s", type(exc).__name__
            )
            response = JSONResponse(
                {"detail": "Internal server error", "request_id": request_id},
                status_code=500,
            )
            await response(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
