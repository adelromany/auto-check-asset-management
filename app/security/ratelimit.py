"""Tiny in-memory rate limiter (single process only).

Only two unauthenticated/high-fan-out endpoints are limited: the agent submit
endpoint and the recipient search. No dependency is added. The counters live
in this process, so a multi-worker deployment needs a shared store later; that
limitation is recorded in ``docs/security-review.md``.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from starlette.responses import JSONResponse

from app import config

SUBMIT_RULE = "session_submit"
SEARCH_RULE = "recipient_search"

_RULES = (
    (re.compile(r"^/api/session/[^/]+/submit$"), SUBMIT_RULE),
    (re.compile(r"^/api/handovers/[^/]+/recipient/search$"), SEARCH_RULE),
)


class SlidingWindowLimiter:
    """Allow at most ``limit`` events per ``window_seconds`` for a key."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        events = self._events[key]
        cutoff = current - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(current)
        return True

    def retry_after(self, key: str, *, now: float | None = None) -> int:
        current = time.monotonic() if now is None else now
        events = self._events.get(key)
        if not events:
            return 0
        return max(1, int(self.window_seconds - (current - events[0])))


class RateLimitMiddleware:
    """Apply the two fixed rules, keyed by client address and rule name."""

    def __init__(self, app):
        self.app = app
        window = float(config.RATE_LIMIT_WINDOW_SECONDS)
        self._limiters = {
            SUBMIT_RULE: SlidingWindowLimiter(
                config.RATE_LIMIT_SUBMIT_PER_WINDOW, window
            ),
            SEARCH_RULE: SlidingWindowLimiter(
                config.RATE_LIMIT_RECIPIENT_SEARCH_PER_WINDOW, window
            ),
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        rule = next((name for pattern, name in _RULES if pattern.match(path)), None)
        if rule is None:
            await self.app(scope, receive, send)
            return

        client = scope.get("client") or ("unknown", 0)
        key = f"{rule}:{client[0]}"
        limiter = self._limiters[rule]
        if limiter.allow(key):
            await self.app(scope, receive, send)
            return

        response = JSONResponse(
            {"detail": "Too many requests; retry later"},
            status_code=429,
            headers={"Retry-After": str(limiter.retry_after(key))},
        )
        await response(scope, receive, send)
