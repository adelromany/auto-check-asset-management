"""Focused proof that primary UI flows really persist their results."""

from __future__ import annotations

from playwright.sync_api import sync_playwright

from tests.e2e.test_capture_screens import REPORT


def test_registration_maintenance_transit_and_case_sync(portal):
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        try:
            page.goto(portal.base + "/handovers?new=1", wait_until="networkidle")
            form = page.locator('[data-new-case-form][data-kind="handover"]')
            form.locator('[name="device_serial"]').fill("TEST-FLOW-H")
            form.locator('[name="ticket_ref"]').fill("FLOW-H")
            assert form.locator('[name="engineer"]').input_value()
            form.locator("[data-primary]").click()
            page.wait_for_url("**/handovers/*", timeout=10000)
            assert "TEST-FLOW-H" in page.locator("h1").inner_text()

            page.goto(portal.base + "/maintenance?new=1", wait_until="networkidle")
            form = page.locator('[data-new-case-form][data-kind="maintenance"]')
            form.locator('[name="device_serial"]').fill("TEST-FLOW-M")
            form.locator('[name="reported_issue"]').fill("Battery expands and stops charging")
            form.locator('[name="diagnosis_category"]').select_option(label="Other")
            form.locator('[name="priority"]').select_option("high")
            form.locator('[name="diagnosis_note"]').fill("Handle with care")
            form.locator("[data-primary]").click()
            page.wait_for_url("**/maintenance/*", timeout=10000)
            case_url = page.url
            assert "TEST-FLOW-M" in page.locator("h1").inner_text()
            assert "High" in page.locator(".passport").inner_text()

            page.goto(portal.base + "/maintenance", wait_until="networkidle")
            card = page.locator("article[data-case-card]").filter(has_text="TEST-FLOW-M")
            card.locator('[data-step="send"]').click()
            send = page.locator('[data-step-form="send"]')
            send.locator('[name="vendor"]').select_option(label="FixTech")
            send.locator('[name="reference"]').fill("RMA-FLOW-1")
            send.locator('[name="expected_return_date"]').fill("2026-12-31")
            send.locator('[name="accessories"]').fill("Power adapter")
            send.locator('[name="condition_notes"]').fill("Chassis scratched")
            send.locator("[data-primary]").click()
            send.wait_for(state="detached", timeout=15000)
            page.locator("article[data-case-card]").first.wait_for(state="visible")
            card = page.locator("article[data-case-card]").filter(has_text="TEST-FLOW-M")
            assert card.locator('[data-step="receive"]').count() == 1

            card.locator('[data-step="receive"]').click()
            receive = page.locator('[data-step-form="receive"]')
            receive.locator('[name="outcome"]').select_option("repaired")
            receive.locator('[name="condition_notes"]').fill("Clean and tested")
            receive.locator('[name="cost"]').fill("180")
            receive.locator('[name="warranty"]').select_option("no")
            receive.locator("[data-primary]").click()
            receive.wait_for(state="detached", timeout=15000)
            page.locator("article[data-case-card]").first.wait_for(state="visible")
            page.goto(case_url, wait_until="domcontentloaded")
            page.locator(".case-chips").wait_for(state="visible")
            assert "Returned" in page.locator(".case-chips").inner_text()
            assert "180" in page.locator(".passport").inner_text()

            # The case drawer renders its own waiting and result states; the
            # linked agent endpoint records the same report on the case.
            page.goto(
                portal.base + f"/handovers/{portal.click_handover_id}",
                wait_until="networkidle",
            )
            page.locator("[data-sync-open]").click()
            page.locator("#sync-drawer-start").click()
            page.locator("#sync-waiting").wait_for(state="visible")
            code = page.locator("#sync-code").inner_text()
            assert page.locator("#sync-cmd-windows").inner_text()
            linked = dict(REPORT, serial="TEST-C1")
            portal.api("POST", f"/api/session/{code}/submit", linked)
            page.locator("#sync-result").wait_for(state="visible", timeout=10000)
            assert "Report attached to this case." in page.locator("#attach-results").inner_text()
            assert "matches" in page.locator("#sync-result-facts").inner_text()
            page.get_by_role("button", name="Done", exact=True).click()
            page.wait_for_load_state("networkidle")
            assert "ThinkPad T14" in page.locator(".passport").inner_text()
        finally:
            browser.close()
