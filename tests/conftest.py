"""Shared fixtures for characterization tests.

Convention (keeps tests green across the Phase 2 refactor):
- Tests access the app ONLY via `import main` + attribute lookup
  (`main.app`, `main.current_user`, `main.oauth`, `main.SSO_ENABLED`).
  Never `from main import <name>` at module top: `importlib.reload`
  re-executes the same module object, so top-level `from`-bindings go stale.
- After the refactor, root `main.py` stays a shim that re-exports these
  names, so every test below keeps working unchanged.
- All env vars the app reads are set explicitly here, so a real developer
  `.env` (with secrets) can never leak into or affect tests.
"""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

BASE_ENV = {
    "SSO_ENABLED": "false",
    "DEV_USER_NAME": "",
    "DEV_USER_EMAIL": "",
    "SESSION_SECRET": "test-secret",
    "HTTPS_ONLY": "false",
    "SESSION_TTL": "600",
    "AZURE_TENANT_ID": "test-tenant",
    "AZURE_CLIENT_ID": "test-id",
    "AZURE_CLIENT_SECRET": "test-secret",
    "REDIRECT_URI": "http://localhost:8080/auth/callback",
    "SNIPEIT_URL": "http://snipeit.test",
    "SNIPEIT_TOKEN": "",
    "APP_HOST": "",
}


def _reload_app_modules():
    """Re-import the app with current env. Gives a fresh session store."""
    if "main" not in sys.modules:
        import main  # noqa: F401
    for name in [n for n in list(sys.modules) if n == "main" or n.startswith("app.")]:
        importlib.reload(sys.modules[name])
    import main
    return main


@pytest.fixture()
def make_client(monkeypatch):
    """Build (TestClient, main_module) with given env overrides.

    Usage: `client, mod = make_client()` or
    `client, mod = make_client(SSO_ENABLED="true", SNIPEIT_TOKEN="x")`.
    Each call reloads the app, so the session store is empty.
    """

    def _make(**overrides):
        env = dict(BASE_ENV)
        env.update(overrides)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        mod = _reload_app_modules()
        return TestClient(mod.app, follow_redirects=False), mod

    return _make


@pytest.fixture()
def sso_off_client(make_client):
    client, _ = make_client()
    return client
