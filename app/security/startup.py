"""Fail-closed configuration checks (SEC-02).

The application must refuse to start when SSO is enabled but the session
cookie is still signed with the public placeholder. A warning is not enough:
a predictable session secret lets anyone forge an engineer identity.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from app import config

_PLACEHOLDER_SECRETS = {"", "change-me"}


def validate_startup_config() -> None:
    """Raise ``RuntimeError`` when the security configuration is unsafe."""
    if not config.SSO_ENABLED:
        pass
    else:
        secret = (config.SESSION_SECRET or "").strip()
        if secret.lower() in _PLACEHOLDER_SECRETS:
            raise RuntimeError(
                "Refusing to start: SSO_ENABLED=true requires a real SESSION_SECRET. "
                "Set SESSION_SECRET to a long random value (for example "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`). "
                "The placeholder value 'change-me' is never accepted."
            )

    if snipeit_url_conflicts_with_portal(
        config.SNIPEIT_URL, config.APP_HOST, config.REDIRECT_URI
    ):
        logging.getLogger(__name__).warning(
            "SNIPEIT_URL points at the portal itself"
        )


def snipeit_url_conflicts_with_portal(
    snipeit_url: str, app_host: str, redirect_uri: str | None
) -> bool:
    """Return whether Snipe-IT resolves to the portal host and port."""
    target = _host_port(snipeit_url)
    candidates = [app_host, redirect_uri or ""]
    return bool(target and any(target == _host_port(item) for item in candidates))


def _host_port(value: str) -> tuple[str, int | None] | None:
    try:
        parts = urlsplit(value if "://" in value else f"http://{value}")
        if not parts.hostname:
            return None
        host = parts.hostname.casefold()
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            host = "<loopback>"
        return host, parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
