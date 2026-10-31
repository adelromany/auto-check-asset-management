"""Portal startup catches an Snipe-IT URL pointed at itself."""

import logging

from app.security.startup import snipeit_url_conflicts_with_portal, validate_startup_config
from app import config


def test_snipeit_url_conflicts_with_portal_listener_or_redirect():
    assert snipeit_url_conflicts_with_portal(
        "http://localhost:8080", "localhost:8080", "http://localhost:8080/auth/callback"
    )
    assert snipeit_url_conflicts_with_portal(
        "http://localhost:8080", "0.0.0.0:8080", "http://localhost:8080/auth/callback"
    )
    assert not snipeit_url_conflicts_with_portal(
        "http://localhost:8081", "localhost:8080", "http://localhost:8080/auth/callback"
    )


def test_startup_warns_for_portal_snipeit_url(monkeypatch, caplog):
    monkeypatch.setattr(config, "SSO_ENABLED", False)
    monkeypatch.setattr(config, "SNIPEIT_URL", "http://localhost:8080")
    monkeypatch.setattr(config, "APP_HOST", "localhost:8080")
    monkeypatch.setattr(config, "REDIRECT_URI", "http://localhost:8080/auth/callback")

    with caplog.at_level(logging.WARNING):
        validate_startup_config()

    assert "SNIPEIT_URL points at the portal itself" in caplog.text
