"""Capture the Phase 7 review matrix from the real, seeded application."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "docs" / "review"
DESKTOP = {"width": 1440, "height": 900}
MOBILE = {"width": 390, "height": 844}

REPORT = {
    "hostname": "TEST-PC",
    "username": "employee",
    "serial": "TEST-H1",
    "manufacturer": "Lenovo",
    "model": "ThinkPad T14",
    "cpu": "Intel Core i7",
    "cpu_cores": 8,
    "ram_gb": 16,
    "disks": [{"name": "NVMe", "size_gb": 512, "type": "SSD"}],
    "os_name": "Windows",
    "os_version": "11 23H2",
    "os_arch": "x64",
    "ip_addresses": [],
    "agent_os": "windows",
    "collected_at": "2026-11-21T10:00:00Z",
    "software_checks": [
        {"id": "chrome", "name": "Chrome", "installed": True,
         "version": "131", "method": "registry"},
        {"id": "vpn", "name": "VPN Client", "installed": False,
         "version": None, "method": "not_found"},
    ],
    "windows_activation": {"status": "Licensed", "status_code": 1,
                           "product_name": "Windows 11 Pro", "partial_key": "ABCDE"},
}


@pytest.fixture(scope="module")
def seeded(portal):
    hid = portal.click_handover_id
    for op in ("device_prepared", "user_signed_in"):
        try:
            portal.api("POST", f"/api/handovers/{hid}/operations/{op}/confirm")
        except Exception:
            pass
    mid = portal.click_maintenance_id
    payload = {
        "reported_issue": "Battery does not hold charge; fan noise under load.",
        "vendor": "FixTech",
        "sent_date": "2026-11-02",
        "reference": "RMA-4471",
        "expected_return_date": "2026-11-20",
        "cost": "180",
        "warranty": "no",
    }
    try:
        portal.api("POST", f"/api/handovers/{mid}/maintenance", payload)
        portal.api("POST", f"/api/handovers/{mid}/operations/sent_out/confirm")
    except Exception:
        pass
    return portal


def _shot(page, name: str, viewport: dict) -> None:
    suffix = "desktop" if viewport is DESKTOP else "mobile"
    page.set_viewport_size(viewport)
    page.wait_for_timeout(250)
    page.screenshot(path=str(OUT / f"{name}-{suffix}.png"), full_page=False)


def _both(page, name: str) -> None:
    for viewport in (DESKTOP, MOBILE):
        _shot(page, name, viewport)


def test_capture(seeded):
    portal = seeded
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for theme in ("light", "dark"):
            ctx = browser.new_context(viewport=DESKTOP)
            page = ctx.new_page()
            page.goto(portal.base + "/", wait_until="networkidle")
            page.evaluate("t => localStorage.setItem('theme', t)", theme)
            page.reload(wait_until="networkidle")

            for path, name in (
                ("/", "dashboard"),
                ("/handovers", "handovers"),
                ("/maintenance", "maintenance"),
                ("/sync", "sync"),
                (f"/handovers/{portal.click_handover_id}", "case"),
                (f"/handovers/{portal.click_handover_id}/history", "history"),
                (f"/maintenance/{portal.click_maintenance_id}", "maintenance-case"),
            ):
                page.goto(portal.base + path, wait_until="networkidle")
                _both(page, f"{name}-{theme}")

            page.goto(portal.base + "/handovers", wait_until="networkidle")
            page.locator("label.view-switch").click()
            _both(page, f"handovers-table-{theme}")
            page.locator("label.view-switch").click()
            page.locator("[data-new-shortcut='handover']").first.click()
            _both(page, f"new-handover-{theme}")
            page.keyboard.press("Escape")

            page.goto(portal.base + "/maintenance", wait_until="networkidle")
            page.locator("[data-maint-tab='atvendors']").click()
            _both(page, f"maintenance-vendors-{theme}")
            page.locator("[data-maint-tab='board']").click()
            page.locator("[data-new-shortcut='maintenance']").click()
            _both(page, f"new-maintenance-{theme}")
            page.keyboard.press("Escape")

            page.goto(
                portal.base + f"/handovers/{portal.click_handover_id}",
                wait_until="networkidle",
            )
            page.locator('[data-op-tile="agent_report"]').click()
            _both(page, f"drawer-open-{theme}")
            page.keyboard.press("Escape")

            page.goto(portal.base + "/sync", wait_until="networkidle")
            page.locator("#sync-start-button").click()
            page.locator("#sync-waiting").wait_for(state="visible")
            _both(page, f"sync-waiting-{theme}")
            code = page.locator("#sync-code").inner_text()
            portal.api("POST", f"/api/session/{code}/submit", REPORT)
            page.locator("#sync-result").wait_for(state="visible", timeout=10000)
            _both(page, f"sync-result-{theme}")

            response = page.goto(portal.base + "/review-page-not-found", wait_until="networkidle")
            assert response.status == 404
            assert "Page not found" in page.locator("h1").inner_text()
            _both(page, f"error-{theme}")
            ctx.close()
        browser.close()
