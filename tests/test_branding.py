"""Branding requirements: b_labs logo, HQ Portal title, no old monitor SVG."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.main

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_topbar_renders_b_labs_image_and_no_monitor_svg(sso_off_client: TestClient) -> None:
    response = sso_off_client.get("/")
    assert response.status_code == 200
    html = response.text

    # Must contain the b_labs logo image
    assert 'src="/static/img/b_labs.jpeg"' in html or "src='/static/img/b_labs.jpeg'" in html
    assert 'alt="b_labs"' in html

    # D6: the mark is never cropped, its size comes from a CSS class (no inline
    # style, which the CSP would block), and the chip is the brand ink.
    assert "logo-chip-32" in html or "logo-chip-40" in html
    assert "object-fit:contain" in (REPO_ROOT / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    ).replace(" ", "")
    assert "style=" not in re.search(
        r"<span class=\"logo-chip[\s\S]*?</span>", html
    ).group(0)
    assert "#1A1A1A" in (REPO_ROOT / "styles" / "app.css").read_text(encoding="utf-8")

    # Must NOT contain the old monitor SVG as branding. The theme toggle keeps
    # a monitor glyph for "follow the system" (a UI affordance, not the logo),
    # so it is stripped before the brand check.
    without_theme_toggle = re.sub(
        r"<button[^>]*data-theme-toggle[\s\S]*?</button>", "", html
    )
    assert '<rect x="3" y="4" width="18" height="12"' not in without_theme_toggle
    assert "M8 20h8" not in without_theme_toggle


def test_snipeit_onboarding_string_is_gone_from_source_trees() -> None:
    """The string 'Snipe-IT Onboarding' is replaced everywhere except external agent.sh or real SnipeIT API."""
    forbidden = "Snipe-IT Onboarding"
    offending_files: list[str] = []

    for directory in ("app", "templates"):
        dir_path = REPO_ROOT / directory
        for path in dir_path.rglob("*"):
            if not path.is_file() or path.suffix in (".pyc", ".png", ".jpeg", ".jpg", ".ico"):
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
            if forbidden.lower() in content.lower():
                offending_files.append(str(path.relative_to(REPO_ROOT)))

    for path in (REPO_ROOT / "static").rglob("*"):
        if not path.is_file() or path.name == "agent.sh" or path.suffix in (".pyc", ".png", ".jpeg", ".jpg", ".ico", ".css"):
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden.lower() in content.lower():
            offending_files.append(str(path.relative_to(REPO_ROOT)))

    assert not offending_files, f"Found '{forbidden}' in: {offending_files}"
