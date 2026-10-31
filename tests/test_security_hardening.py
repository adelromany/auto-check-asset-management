"""Phase 8: fail-closed startup, CSRF/origin, headers, limits and secrets."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import app.main
from app import config
from app.security.csrf import CsrfMiddleware, get_or_create_token
from app.security.headers import CONTENT_SECURITY_POLICY, SecurityHeadersMiddleware
from app.security.ratelimit import RateLimitMiddleware, SlidingWindowLimiter
from app.security.startup import validate_startup_config

REPO_ROOT = Path(__file__).resolve().parents[1]


# -- fail closed ------------------------------------------------------------


@pytest.mark.parametrize("secret", ["", "change-me", "CHANGE-ME", "   "])
def test_startup_refuses_placeholder_session_secret(monkeypatch, secret) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", secret)

    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        validate_startup_config()
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        app.main.create_app()


def test_startup_accepts_a_real_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    monkeypatch.setattr(config, "SESSION_SECRET", "x" * 64)

    validate_startup_config()
    application = app.main.create_app()
    assert application.title == "Snipe-IT Onboarding"


def test_development_bypass_does_not_require_a_secret(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", False)
    monkeypatch.setattr(config, "SESSION_SECRET", "change-me")

    validate_startup_config()


# -- headers / CSP ----------------------------------------------------------


def test_security_headers_on_api_and_pages(sso_off_client) -> None:
    for path in ("/api/health", "/"):
        response = sso_off_client.get(path)
        assert response.status_code == 200, path
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_csp_is_self_only() -> None:
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY
    assert "http:" not in CONTENT_SECURITY_POLICY
    assert "https:" not in CONTENT_SECURITY_POLICY
    assert "script-src 'self'" in CONTENT_SECURITY_POLICY
    assert "style-src 'self'" in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY


def test_landing_page_has_no_external_hosts(sso_off_client) -> None:
    response = sso_off_client.get("/")

    assert response.status_code == 200
    assert "fonts.googleapis.com" not in response.text
    assert "fonts.gstatic.com" not in response.text
    assert "theme-init.js" in response.text


# -- CSRF / origin ----------------------------------------------------------


def _csrf_app() -> FastAPI:
    application = FastAPI()

    @application.get("/api/me")
    async def me(request: Request, response: Response):
        token = get_or_create_token(request)
        response.headers["X-CSRF-Token"] = token
        return {"csrf_token": token}

    @application.post("/api/handovers/example")
    async def write():
        return {"ok": True}

    @application.post("/api/session/{code}/submit")
    async def submit(code: str):
        return {"ok": True, "code": code}

    application.add_middleware(CsrfMiddleware)
    application.add_middleware(
        SessionMiddleware, secret_key="test-secret", https_only=False, same_site="lax"
    )
    application.add_middleware(SecurityHeadersMiddleware)
    return application


def _token(client: TestClient) -> str:
    response = client.get("/api/me")
    assert response.status_code == 200
    return response.headers["X-CSRF-Token"]


def test_csrf_token_is_stable_per_session(sso_off_client) -> None:
    first = sso_off_client.get("/api/me").headers["X-CSRF-Token"]
    second = sso_off_client.get("/api/me").headers["X-CSRF-Token"]

    assert first and first == second


def test_protected_write_requires_csrf_token(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    client = TestClient(_csrf_app())
    token = _token(client)

    missing = client.post("/api/handovers/example")
    wrong = client.post("/api/handovers/example", headers={"X-CSRF-Token": "wrong"})
    valid = client.post("/api/handovers/example", headers={"X-CSRF-Token": token})

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert valid.status_code == 200


def test_protected_write_rejects_a_foreign_origin(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    client = TestClient(_csrf_app())
    token = _token(client)

    foreign = client.post(
        "/api/handovers/example",
        headers={"X-CSRF-Token": token, "Origin": "http://evil.example"},
    )
    same = client.post(
        "/api/handovers/example",
        headers={"X-CSRF-Token": token, "Origin": "http://testserver"},
    )

    assert foreign.status_code == 403
    assert foreign.json()["detail"] == "Origin not allowed"
    assert same.status_code == 200


def test_agent_submit_is_excluded_from_csrf(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    client = TestClient(_csrf_app())

    response = client.post("/api/session/ABC123/submit")

    assert response.status_code == 200


def test_csrf_is_skipped_when_sso_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config, "SSO_ENABLED", False)
    client = TestClient(_csrf_app())

    response = client.post("/api/handovers/example")

    assert response.status_code == 200


# -- rate limit -------------------------------------------------------------


def test_sliding_window_limiter() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)

    assert limiter.allow("k", now=0)
    assert limiter.allow("k", now=1)
    assert not limiter.allow("k", now=2)
    assert limiter.retry_after("k", now=2) >= 1
    assert limiter.allow("k", now=61)


def test_submit_endpoint_is_rate_limited(monkeypatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_SUBMIT_PER_WINDOW", 2)
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW_SECONDS", 60)
    application = FastAPI()

    @application.post("/api/session/{code}/submit")
    async def submit(code: str):
        return {"ok": True}

    application.add_middleware(RateLimitMiddleware)
    client = TestClient(application)

    first = client.post("/api/session/ABC123/submit")
    second = client.post("/api/session/ABC123/submit")
    third = client.post("/api/session/ABC123/submit")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["retry-after"]


# -- secrets scan -----------------------------------------------------------

_SECRET_PATTERNS = [
    re.compile(
        r"(?m)^\s*(?:SNIPEIT_TOKEN|AZURE_CLIENT_SECRET|SESSION_SECRET)\s*=\s*"
        r"(?P<value>[A-Za-z0-9_\-]{16,})\s*$",
        re.IGNORECASE,
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
]


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("git is not available; tracked-file scan cannot run")
    names = [name for name in result.stdout.decode("utf-8").split("\0") if name]
    return [REPO_ROOT / name for name in names]


def test_no_tracked_file_contains_an_obvious_secret() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(text):
                offenders.append(path.relative_to(REPO_ROOT).as_posix())
                break

    assert not offenders, f"possible secrets in tracked files: {sorted(set(offenders))}"
