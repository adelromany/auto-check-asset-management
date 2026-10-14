"""Characterization tests: pin CURRENT behavior before the refactor.

Every assertion below describes what the app does today on `feature/sso`.
Phase 2 must keep all of them green without modification.

Notes:
- No network is used. Entra calls are never made (SSO-off mode, or the
  authlib redirect is stubbed). Snipe-IT HTTP is faked by patching
  `httpx.AsyncClient` globally (works no matter which module imports it).
- There is no report/handover-sheet/email code in the repo (the plan §4
  assumed it), so instead the agent round-trip pins the Phase-3 payload
  additions (`software_checks`, `windows_activation`) as passthrough data.
"""

import re

import httpx
import pytest

CODE_RE = re.compile(r"^[A-Z0-9]{2}-[A-Z0-9]{2}-[A-Z0-9]{2}$")

FULL_PAYLOAD = {
    "hostname": "PC-01",
    "username": "alice",
    "serial": "SN123456",
    "manufacturer": "Lenovo",
    "model": "ThinkPad T14",
    "cpu": "Intel i7",
    "cpu_cores": 8,
    "ram_gb": 16.0,
    "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
    "os_name": "Windows",
    "os_version": "11",
    "os_arch": "x64",
    "ip_addresses": [{"iface": "Wi-Fi", "ip": "192.168.1.50"}],
    "agent_os": "windows",
    "collected_at": "2026-01-01T00:00:00Z",
    "software_checks": [
        {"id": "chrome", "name": "Chrome", "installed": True,
         "version": "120.0", "method": "registry"},
        {"id": "vpn", "name": "VPN Client", "installed": False,
         "version": None, "method": "not_found"},
    ],
    "windows_activation": {"status": "Licensed", "status_code": 1,
                           "product_name": "Windows 11 Pro", "partial_key": "ABCDE"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_code(client):
    r = client.get("/api/session/new")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"code", "ttl_seconds"}
    assert CODE_RE.match(body["code"]), body["code"]
    assert isinstance(body["ttl_seconds"], int)
    return body["code"]


class FakeHTTPXResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def is_success(self):
        return 200 <= self.status_code < 400

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://snipeit.test/api/v1/hardware")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("fake", request=request, response=response)

    def json(self):
        return self._payload


def fake_async_client_factory(payload, status_code=200):
    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            return FakeHTTPXResponse(payload, status_code)

    return FakeAsyncClient


SNIPE_ROWS = {
    "rows": [
        {"asset_tag": "A-1", "name": "Laptop 1", "serial": "SN123456",
         "status_label": {"name": "Ready"},
         "model": {"name": "ThinkPad T14"}, "category": {"name": "Laptops"},
         "manufacturer": {"name": "Lenovo"}, "assigned_to": {"name": "Alice"},
         "location": {"name": "HQ"}, "last_checkout": "2026-01-02",
         "purchase_date": {"formatted": "2024-01-01"},
         "warranty_months": 36, "notes": "ok"},
        {"asset_tag": "A-2", "name": "Laptop 2", "serial": "OTHER",
         "status_label": None, "model": None, "category": None,
         "manufacturer": None, "assigned_to": None, "location": None,
         "last_checkout": None, "purchase_date": None,
         "warranty_months": None, "notes": None},
    ]
}


# ---------------------------------------------------------------------------
# Health / pages
# ---------------------------------------------------------------------------

def test_health_shape(sso_off_client):
    r = sso_off_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"status", "time", "sessions_active"}
    assert body["status"] == "ok"
    assert body["sessions_active"] == 0


def test_index_200_when_sso_off(sso_off_client):
    r = sso_off_client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "agent-slot" in r.text  # page shell marker


def test_index_redirects_when_sso_on(make_client):
    client, _ = make_client(SSO_ENABLED="true")
    r = client.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/login"


def test_logout_always_redirects_home(sso_off_client):
    r = sso_off_client.get("/logout")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/"


# ---------------------------------------------------------------------------
# /api/me
# ---------------------------------------------------------------------------

def test_me_dev_user_when_sso_off(sso_off_client):
    r = sso_off_client.get("/api/me")
    assert r.status_code == 200
    assert r.json() == {"name": "Dev User", "email": "dev@local", "sso": False}


def test_me_401_when_sso_on(make_client):
    client, _ = make_client(SSO_ENABLED="true")
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json() == {"detail": "Login required"}


# ---------------------------------------------------------------------------
# Session-code agent flow
# ---------------------------------------------------------------------------

def test_new_session_shape(sso_off_client):
    new_code(sso_off_client)


def test_code_format_sample(sso_off_client):
    for _ in range(20):
        assert CODE_RE.match(new_code(sso_off_client))


def test_poll_waiting_then_ready(sso_off_client):
    code = new_code(sso_off_client)
    r = sso_off_client.get(f"/api/session/{code}/data")
    assert r.status_code == 202
    assert r.json() == {"status": "waiting"}

    r = sso_off_client.post(f"/api/session/{code}/submit", json=FULL_PAYLOAD)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    r = sso_off_client.get(f"/api/session/{code}/data")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    # full payload round-trips, including software/activation additions
    for key, value in FULL_PAYLOAD.items():
        assert body["data"][key] == value


def test_submit_idempotent(sso_off_client):
    code = new_code(sso_off_client)
    assert sso_off_client.post(f"/api/session/{code}/submit",
                               json={"hostname": "h"}).json() == {"status": "ok"}
    assert sso_off_client.post(f"/api/session/{code}/submit",
                               json={"hostname": "h"}).json() == {"status": "already_submitted"}


def test_unknown_code_404(sso_off_client):
    assert sso_off_client.get("/api/session/XX-XX-XX/data").status_code == 404
    r = sso_off_client.post("/api/session/XX-XX-XX/submit", json={"hostname": "t"})
    assert r.status_code == 404  # agent route is never 401


def test_expired_session_404(make_client):
    client, _ = make_client(SESSION_TTL="-5")
    code = new_code(client)
    assert client.get(f"/api/session/{code}/data").status_code == 404


def test_poll_isolation_403(make_client):
    import main
    client, mod = make_client()
    code = new_code(client)
    # same user can poll (202, not 403)
    assert client.get(f"/api/session/{code}/data").status_code == 202
    # a different engineer gets 403
    mod.app.dependency_overrides[mod.current_user] = lambda: {"name": "Other", "email": "other@x"}
    try:
        r = client.get(f"/api/session/{code}/data")
        assert r.status_code == 403
    finally:
        mod.app.dependency_overrides.clear()


def test_protected_routes_401_when_sso_on(make_client):
    client, _ = make_client(SSO_ENABLED="true")
    assert client.get("/api/session/new").status_code == 401
    assert client.get("/api/snipeit/device?serial=SN123456").status_code == 401


# ---------------------------------------------------------------------------
# SSO routes, offline
# ---------------------------------------------------------------------------

def test_login_redirects_home_when_sso_off(sso_off_client):
    r = sso_off_client.get("/login")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/"


def test_callback_redirects_home_when_sso_off(sso_off_client):
    r = sso_off_client.get("/auth/callback")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/"


def test_login_builds_entra_redirect_when_sso_on(make_client, monkeypatch):
    import main
    client, mod = make_client(SSO_ENABLED="true")

    async def fake_redirect(request, redirect_uri):
        from fastapi.responses import RedirectResponse
        assert redirect_uri == "http://localhost:8080/auth/callback"
        return RedirectResponse(
            "https://login.microsoftonline.com/test-tenant/oauth2/v2.0/authorize?client_id=test-id")

    monkeypatch.setattr(mod.oauth.entra, "authorize_redirect", fake_redirect)
    r = client.get("/login")
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("https://login.microsoftonline.com/")


# ---------------------------------------------------------------------------
# Snipe-IT proxy
# ---------------------------------------------------------------------------

def test_lookup_400_short_serial(sso_off_client):
    assert sso_off_client.get("/api/snipeit/device?serial=x").status_code == 400
    assert sso_off_client.get("/api/snipeit/device?serial=%20%20").status_code == 400


def test_lookup_503_without_token(sso_off_client):
    r = sso_off_client.get("/api/snipeit/device?serial=SN123456")
    assert r.status_code == 503


def test_lookup_exact_match_shape(make_client, monkeypatch):
    client, _ = make_client(SNIPEIT_TOKEN="tok")
    monkeypatch.setattr("httpx.AsyncClient", fake_async_client_factory(SNIPE_ROWS))
    r = client.get("/api/snipeit/device?serial=SN123456")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["asset_tag"] == "A-1"  # exact serial wins over first row
    assert body["serial"] == "SN123456"
    assert body["status"] == "Ready"
    assert body["assigned_to"] == "Alice"
    assert body["purchase_date"] == "2024-01-01"
    assert set(body.keys()) == {"found", "asset_tag", "name", "serial", "status",
                                "model", "category", "manufacturer", "assigned_to",
                                "location", "last_checkout", "purchase_date",
                                "warranty_months", "notes"}


def test_lookup_first_row_when_no_exact_match(make_client, monkeypatch):
    client, _ = make_client(SNIPEIT_TOKEN="tok")
    monkeypatch.setattr("httpx.AsyncClient", fake_async_client_factory(SNIPE_ROWS))
    r = client.get("/api/snipeit/device?serial=ZZZ999")
    assert r.status_code == 200
    assert r.json()["asset_tag"] == "A-1"


def test_lookup_404_when_no_rows(make_client, monkeypatch):
    client, _ = make_client(SNIPEIT_TOKEN="tok")
    monkeypatch.setattr("httpx.AsyncClient", fake_async_client_factory({"rows": []}))
    assert client.get("/api/snipeit/device?serial=SN123456").status_code == 404


def test_snipeit_health_no_token(sso_off_client):
    assert sso_off_client.get("/api/snipeit/health").json() == {
        "connected": False, "reason": "token_not_configured"}


def test_snipeit_health_connected(make_client, monkeypatch):
    client, _ = make_client(SNIPEIT_TOKEN="tok")
    monkeypatch.setattr("httpx.AsyncClient", fake_async_client_factory({"rows": []}))
    body = client.get("/api/snipeit/health").json()
    assert body["connected"] is True
    assert body["reason"] is None


def test_snipeit_health_unreachable(make_client, monkeypatch):
    import httpx as _httpx

    class DownClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **k):
            raise _httpx.ConnectError("down")

    client, _ = make_client(SNIPEIT_TOKEN="tok")
    monkeypatch.setattr("httpx.AsyncClient", DownClient)
    assert client.get("/api/snipeit/health").json() == {
        "connected": False, "reason": "unreachable"}
