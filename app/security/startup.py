"""Fail-closed configuration checks (SEC-02).

The application must refuse to start when SSO is enabled but the session
cookie is still signed with the public placeholder. A warning is not enough:
a predictable session secret lets anyone forge an engineer identity.
"""

from __future__ import annotations

from app import config

_PLACEHOLDER_SECRETS = {"", "change-me"}


def validate_startup_config() -> None:
    """Raise ``RuntimeError`` when the security configuration is unsafe."""
    if not config.SSO_ENABLED:
        return

    secret = (config.SESSION_SECRET or "").strip()
    if secret.lower() in _PLACEHOLDER_SECRETS:
        raise RuntimeError(
            "Refusing to start: SSO_ENABLED=true requires a real SESSION_SECRET. "
            "Set SESSION_SECRET to a long random value (for example "
            "`python -c \"import secrets; print(secrets.token_hex(32))\"`). "
            "The placeholder value 'change-me' is never accepted."
        )
