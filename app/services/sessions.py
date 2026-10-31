"""In-memory session-code store.

Replaces the module-level `_sessions` dict from main.py with identical
semantics. TTL eviction runs on every operation, exactly like the old
`_purge_expired()` calls. For multi-worker production, swap this class
for a Redis/SQLite implementation — the routers stay untouched.
"""

import random
import string
import time


class SessionStore:
    """{code: {"created": float, "data": dict|None, "tech": dict}}"""

    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._sessions: dict[str, dict] = {}

    # -- introspection ----------------------------------------------------
    def active_count(self) -> int:
        return len(self._sessions)

    # -- lifecycle --------------------------------------------------------
    def purge_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self._sessions.items()
                   if now - v["created"] > self._ttl]
        for k in expired:
            del self._sessions[k]

    @staticmethod
    def make_code() -> str:
        """Human-readable 6-character code, e.g. A7-X3-Q9."""
        chars = string.ascii_uppercase + string.digits
        raw = "".join(random.choices(chars, k=6))
        return f"{raw[0:2]}-{raw[2:4]}-{raw[4:6]}"

    def create(self, tech: dict, handover_id: str | None = None) -> tuple[str, int]:
        """Create a session, return (code, ttl_seconds).

        ``handover_id`` is optional: without it the session behaves exactly as
        before and the agent submit path never touches the database.
        """
        self.purge_expired()
        code = self.make_code()
        # Extremely unlikely collision, but guard anyway
        while code in self._sessions:
            code = self.make_code()
        self._sessions[code] = {
            "created": time.time(),
            "data": None,
            "tech": tech,
            "handover_id": handover_id,
        }
        return code, self._ttl

    def get(self, code: str) -> dict | None:
        self.purge_expired()
        return self._sessions.get(code)

    def submit(self, code: str, data: dict) -> str | None:
        """Store agent data. Returns 'ok', 'already_submitted', or None (unknown)."""
        self.purge_expired()
        session = self._sessions.get(code)
        if not session:
            return None
        if session["data"] is not None:
            # Already submitted — idempotent, just return OK
            return "already_submitted"
        session["data"] = data
        return "ok"
