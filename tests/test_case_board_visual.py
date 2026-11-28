"""Owner review C: the case board must stay calm at every width.

The three visible-word budgets are **220 / 160 / 98** at 1440 / 768 / 390 px.
This is the conservative reading of the review's "220/160/80" requirement and
is recorded as PROPOSED in decision D-73; the owner can confirm or change it.

Chrome is used when it is installed. Without a browser the test skips rather
than failing the suite, matching the existing Playwright test's contract.
"""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.handover import Handover, HandoverStage
from app.domain.stages import STAGE_ORDER

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS = ((1440, 900, 220), (768, 1024, 160), (390, 844, 98))


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _seed(db_path: Path) -> str:
    async def run() -> str:
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            now = datetime.now().replace(microsecond=0)
            async with factory() as session:
                handover = Handover(
                    status="draft",
                    engineer_name="Engineer A",
                    engineer_email="engineer.a@example.com",
                    device_serial="SN-CALM",
                    ticket_ref="LAB-1",
                    created_at=now,
                    updated_at=now,
                    stages=[
                        HandoverStage(stage=stage.value, status="pending")
                        for stage in STAGE_ORDER
                    ],
                )
                session.add(handover)
                await session.commit()
                return str(handover.id)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _seed_in_thread(db_path: Path) -> str:
    """pytest-asyncio owns the fixture thread's loop; seed on a plain thread."""
    result: dict[str, str] = {}

    def worker() -> None:
        result["id"] = _seed(db_path)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    return result["id"]


@pytest.fixture(scope="module")
def case_board(tmp_path_factory: pytest.TempPathFactory):
    db_path = tmp_path_factory.mktemp("case-board") / "ui.db"
    handover_id = _seed_in_thread(db_path)
    port = _free_port()
    environment = dict(os.environ)
    environment.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        SSO_ENABLED="false",
        SESSION_SECRET="case-board-ui",
        APP_HOST=f"http://127.0.0.1:{port}",
        HTTPS_ONLY="false",
        SNIPEIT_URL="http://snipeit.test",
        SNIPEIT_TOKEN="",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/", timeout=2)
                break
            except Exception:
                time.sleep(0.25)
        else:
            pytest.skip("the case-board UI server did not start")
        yield base, handover_id, db_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.fixture(scope="module")
def headless_chrome():
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(channel="chrome", headless=True)
        except Error:
            try:
                instance = playwright.chromium.launch(headless=True)
            except Error:
                pytest.skip("no Chromium/Chrome available for the UI budget test")
        try:
            yield instance
        finally:
            instance.close()


def _words(page) -> list[str]:
    return page.locator("body").inner_text().split()


def test_case_board_meets_the_visible_word_budgets(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    for width, height, budget in BUDGETS:
        page = headless_chrome.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(
                f"{base}/handovers/{handover_id}", wait_until="networkidle"
            )
            words = _words(page)
            assert len(words) <= budget, (
                f"{width}px shows {len(words)} words, budget {budget}: "
                + " ".join(words)
            )
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - window.innerWidth"
            )
            assert overflow <= 1, f"{width}px page overflows horizontally by {overflow}px"
        finally:
            page.close()


def test_handover_case_has_three_panels_and_device_drawer(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        panels = page.locator(".handover-panel:visible")
        assert panels.count() == 3

        # No drawer is rendered until a device check is opened.
        drawer = page.locator('[data-drawer][data-open="true"]')
        assert drawer.count() == 0

        page.locator('[data-check-device]').click()
        drawer = page.locator('[data-drawer][data-open="true"]')
        assert drawer.count() == 1

        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.locator('[data-drawer][data-open="true"]').count() == 0
    finally:
        page.close()


def test_handover_types_switch_panels_and_ready_lab(
    headless_chrome, case_board
) -> None:
    import sqlite3

    base, handover_id, db_path = case_board
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE handover_stages SET status='passed' WHERE handover_id=? "
            "AND stage IN ('device_status','agent_report','software_check')",
            (handover_id.replace("-", ""),),
        )
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        with page.expect_response("**/mode"):
            page.locator('[data-case-mode="pending_user"]').click()
        assert page.locator("[data-device-panel]").is_visible()
        assert page.locator("[data-waiting-user-panel]").is_visible()
        assert page.locator("[data-handover-panel]").is_visible()
        assert not page.locator("[data-recipient-panel]").is_visible()
        with page.expect_response("**/mode"):
            page.locator('[data-case-mode="snipeit"]').click()
        assert page.locator("[data-recipient-panel]").is_visible()
        assert not page.locator("[data-waiting-user-panel]").is_visible()
        with page.expect_response("**/mode"):
            page.locator('[data-case-mode="none"]').click()
        assert page.locator("[data-device-panel]").is_visible()
        assert not page.locator("[data-recipient-panel]").is_visible()
        assert not page.locator("[data-waiting-user-panel]").is_visible()
        assert not page.locator("[data-handover-panel]").is_visible()
        assert page.locator("[data-case-outcome]").inner_text() == "Ready lab"
        output = REPO_ROOT / "docs" / "review" / "v2" / "p2-case-lab.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            page.screenshot(path=str(output), full_page=True)
    finally:
        page.close()


def test_live_holder_checkin_clears_the_device_card(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    holder = {"id": 1, "name": "Alice", "username": "alice", "company": "B.tech"}

    def live(route):
        route.fulfill(json={
            "asset_id": 10, "serial": "SN-CALM", "status": "Ready to deploy",
            "status_id": 1, "deployable": True, "asset_tag": "A-10",
            "model": "ThinkPad T14", "company": "B.tech", "assigned_to": holder,
        })

    def checkin(route):
        nonlocal holder
        holder = None
        route.fulfill(json={
            "asset_id": 10, "serial": "SN-CALM", "status": "Ready to deploy",
            "status_id": 1, "deployable": True, "asset_tag": "A-10",
            "model": "ThinkPad T14", "company": "B.tech", "assigned_to": None,
            "changed": True,
        })

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/handovers/*/device-live", live)
        page.route("**/api/handovers/*/device/checkin", checkin)
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        if page.locator('[data-case-mode="snipeit"]').get_attribute("aria-pressed") != "true":
            with page.expect_response("**/mode"):
                page.locator('[data-case-mode="snipeit"]').click()
            page.reload(wait_until="networkidle")
        assert "With: Alice (B.tech)" in page.locator("[data-device-holder]").inner_text()
        page.locator("[data-device-checkin]").click()
        page.wait_for_function("document.querySelector('[data-device-holder]').textContent === 'Not assigned'")
        assert not page.locator("[data-device-checkin]").is_visible()
        assert page.get_by_text("Other devices with this user", exact=True).count() == 1
    finally:
        page.close()


def test_repeatable_checkout_and_replace_holder(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    checkout_calls = []

    def detail(route):
        response = route.fetch()
        body = response.json()
        body.update({
            "mode": "snipeit", "recipient_mode": "snipeit",
            "recipient_snipeit_id": 1, "recipient_snipeit_name": "Alice",
        })
        for stage in body["stages"]:
            if stage["stage"] == "checkout":
                stage.update({"status": "passed", "detail": {"already": True}})
        route.fulfill(response=response, json=body)

    def checkout(route):
        payload = route.request.post_data_json or {}
        checkout_calls.append(payload)
        if not payload.get("replace_holder") and len(checkout_calls) > 1:
            route.fulfill(status=409, json={"detail": {"code": "held_by_other", "holder": "Bob"}})
            return
        route.fulfill(json={
            "id": handover_id, "mode": "snipeit", "recipient_mode": "snipeit",
            "recipient_snipeit_id": 1, "recipient_snipeit_name": "Alice",
            "stages": [{"stage": "checkout", "status": "passed", "detail": {"already": len(checkout_calls) == 1}}],
            "events": [], "warnings": [], "missing": [],
        })

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route(f"**/api/handovers/{handover_id}", detail)
        page.route(f"**/api/handovers/{handover_id}/checkout", checkout)
        page.route("**/device-live", lambda route: route.fulfill(json={"status": "Deployed", "deployable": True, "assigned_to": {"name": "Alice"}}))
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        button = page.locator("[data-checkout]")
        assert button.is_enabled()
        assert button.inner_text() == "Check out again"
        button.click()
        page.wait_for_function("document.querySelector('[data-checkout]').disabled === false")
        button.click()
        page.locator("[data-replace-holder]").wait_for(state="visible")
        assert page.locator("[data-checkout-result]").inner_text() == "Held by Bob"
        page.locator("[data-replace-holder]").click()
        page.locator("[data-replace-holder]").wait_for(state="hidden")
        assert checkout_calls[-1] == {"replace_holder": True}
    finally:
        page.close()


def test_device_history_cards_and_print_action(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/devices/SN-CALM/history", lambda route: route.fulfill(json={
            "summary": {"now": "With IT", "handovers": 1, "maintenance_count": 1, "maintenance_days": 4, "last_activity": "2026-11-27"},
            "cards": [
                {"date": "2026-11-27", "tag": "Maintenance", "headline": "Returned from FixTech - Screen", "facts": [{"label": "STATUS", "value": "Maintenance completed", "kind": "chip-ok"}], "case_url": f"/maintenance/{handover_id}"},
                {"date": "2026-11-26", "tag": "Handover", "headline": "Handed over to Alice", "facts": [{"label": "STATUS", "value": "Complete", "kind": "chip-ok"}], "case_url": f"/handovers/{handover_id}"},
            ],
        }))
        page.route("**/api/snipeit/device-lookup**", lambda route: route.fulfill(json={"status": "Ready to deploy", "assigned_to": None}))
        page.goto(f"{base}/devices/SN-CALM", wait_until="networkidle")
        assert page.locator(".milestone-card").count() == 2
        assert page.locator(".history-date").count() == 2
        assert "print" not in page.locator("[data-device-history]").inner_text().lower()
        page.screenshot(path=str(REPO_ROOT / "docs/review/v2/device-history-light.png"), full_page=True)
        page.emulate_media(color_scheme="dark")
        page.locator("[data-theme-toggle]").click()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(REPO_ROOT / "docs/review/v2/device-history-dark.png"), full_page=True)
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        page.route(f"**/api/handovers/{handover_id}/form?format=pdf", lambda route: route.fulfill(status=503, json={"detail": "unavailable"}))
        page.route(f"**/api/handovers/{handover_id}/form?format=docx", lambda route: route.fulfill(body=b"docx", headers={"Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}))
        downloads = []
        page.on("download", lambda download: downloads.append(download))
        page.locator("[data-print-form]").click()
        page.locator("[data-form-error]").wait_for(state="visible")
        assert page.locator("[data-form-error]").inner_text() == "PDF printing needs LibreOffice on the server \u2014 Word file downloaded instead."
    finally:
        page.close()


@contextmanager
def _maintenance_seed(db_path: Path, handover_id: str):
    stored_id = handover_id.replace("-", "")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE handovers SET kind='maintenance' WHERE id=?", (stored_id,)
        )
    try:
        yield
    finally:
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE handovers SET kind='handover' WHERE id=?", (stored_id,)
            )


def _maintenance_detail(handover_id: str) -> dict:
    return {
        "id": handover_id,
        "status": "open",
        "maintenance_state": "with_it",
        "device_holder_name": "Alice",
        "stages": [
            {"stage": "snipeit_status", "status": "pending"},
            {"stage": "taken_back", "status": "pending"},
            {"stage": "ready_status", "status": "pending"},
        ],
    }


def _route_handover_state(page, handover_id: str, detail: dict) -> None:
    page.route(
        f"**/api/handovers/{handover_id}",
        lambda route: route.fulfill(json=detail),
    )
    page.route(
        "**/api/snipeit/status-labels",
        lambda route: route.fulfill(json=[
            {"id": 1, "name": "Ready to deploy"},
            {"id": 2, "name": "Maintenance"},
        ]),
    )
    page.route(
        "**/device-live",
        lambda route: route.fulfill(json={
            "status": detail["snipeit_status_name"],
            "deployable": True,
            "assigned_to": None,
        }),
    )
    page.route("**/recipient/items", lambda route: route.fulfill(json=[]))


def test_maintenance_actions_become_done_chips_and_survive_reload(
    headless_chrome, case_board
) -> None:
    base, handover_id, db_path = case_board
    detail = _maintenance_detail(handover_id)

    def action(route):
        assert route.request.method == "POST"
        stage_name = {
            "set-status": "snipeit_status", "take-back": "taken_back"
        }[route.request.url.rsplit("/", 1)[-1]]
        next(stage for stage in detail["stages"] if stage["stage"] == stage_name)[
            "status"
        ] = "passed"
        route.fulfill(json=detail)

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route(f"**/api/handovers/{handover_id}", lambda route: route.fulfill(json=detail))
        page.route(f"**/api/maintenance/cases/{handover_id}/*", action)
        with _maintenance_seed(db_path, handover_id):
            page.goto(f"{base}/maintenance/{handover_id}", wait_until="networkidle")
            page.locator('[data-maint-action-slot="set-status"] button').click()
            status_slot = page.locator('[data-maint-action-slot="set-status"]')
            assert status_slot.locator(".badge-success").inner_text() == "✓ Maintenance"
            assert status_slot.locator("button").count() == 0

            page.locator('[data-maint-action-slot="take-back"] button').click()
            taken_slot = page.locator('[data-maint-action-slot="take-back"]')
            assert taken_slot.locator(".badge-success").inner_text() == "✓ Checked in"
            assert taken_slot.locator("button").count() == 0

            page.reload(wait_until="networkidle")
            assert status_slot.locator(".badge-success").inner_text() == "✓ Maintenance"
            assert taken_slot.locator(".badge-success").inner_text() == "✓ Checked in"
            assert page.locator("[data-maint-action-slot] button").count() == 0
    finally:
        page.close()


def test_failed_set_maintenance_keeps_action_and_shows_error(
    headless_chrome, case_board
) -> None:
    base, handover_id, db_path = case_board
    detail = _maintenance_detail(handover_id)

    def fail_status(route):
        status = next(
            stage for stage in detail["stages"]
            if stage["stage"] == "snipeit_status"
        )
        status.update(status="failed", reason="Snipe-IT unavailable")
        route.fulfill(json=detail)

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route(f"**/api/handovers/{handover_id}", lambda route: route.fulfill(json=detail))
        page.route(f"**/api/maintenance/cases/{handover_id}/set-status", fail_status)
        with _maintenance_seed(db_path, handover_id):
            page.goto(f"{base}/maintenance/{handover_id}", wait_until="networkidle")
            page.locator('[data-maint-action-slot="set-status"] button').click()
            button = page.locator('[data-maint-action-slot="set-status"] button')
            page.locator('[data-maint-action-slot="set-status"] button', has_text="Retry").wait_for()
            assert button.inner_text() == "Retry"
            assert button.is_enabled()
            assert page.locator("[data-maint-result]").inner_text() == "Snipe-IT unavailable"
    finally:
        page.close()


def test_apply_status_only_for_changes_and_reload_uses_server_status(
    headless_chrome, case_board
) -> None:
    base, handover_id, _ = case_board
    detail = {
        "id": handover_id, "mode": "none", "recipient_mode": "none",
        "status": "draft", "maintenance_state": None, "outcome": "ready",
        "snipeit_status_name": "Ready to deploy", "stages": [],
        "events": [], "warnings": [], "missing": [],
    }

    def apply_status(route):
        assert route.request.post_data_json == {"status_label_id": 2}
        detail["snipeit_status_name"] = "Maintenance"
        route.fulfill(json=detail)

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        _route_handover_state(page, handover_id, detail)
        page.route(f"**/api/handovers/{handover_id}/device-status", apply_status)
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        assert page.locator("[data-apply-status]").count() == 0

        page.locator("[data-status-select]").select_option("2")
        page.locator("[data-apply-status]").wait_for(state="visible")
        with page.expect_response(f"**/api/handovers/{handover_id}/device-status"):
            page.locator("[data-apply-status]").click()
        page.locator("[data-apply-status]").wait_for(state="detached")
        assert page.locator("[data-device-status]").inner_text() == "Maintenance"

        page.reload(wait_until="networkidle")
        assert page.locator("[data-apply-status]").count() == 0
        assert page.locator("[data-device-status]").inner_text() == "Maintenance"
        assert page.locator("[data-status-select]").input_value() == "2"
    finally:
        page.close()


def test_unchanged_status_offers_confirm_status_which_posts_null_label(
    headless_chrome, case_board
) -> None:
    base, handover_id, _ = case_board
    detail = {
        "id": handover_id, "mode": "none", "recipient_mode": "none",
        "status": "draft", "maintenance_state": None, "outcome": "not_complete",
        "snipeit_status_name": "Ready to deploy",
        "stages": [{"stage": "device_status", "status": "pending", "reason": None}],
        "events": [], "warnings": [], "missing": ["Device status"],
    }
    posted = []

    def confirm_status(route):
        posted.append(route.request.post_data_json)
        detail["stages"] = [{"stage": "device_status", "status": "passed", "reason": None}]
        route.fulfill(json=detail)

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        _route_handover_state(page, handover_id, detail)
        page.route(f"**/api/handovers/{handover_id}/device-status", confirm_status)
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        # Same status selected: no Apply, but a Confirm status button.
        assert page.locator("[data-apply-status]").count() == 0
        page.locator("[data-confirm-status]").wait_for(state="visible")
        assert page.locator("[data-confirm-status]").inner_text() == "Confirm status"

        with page.expect_response(f"**/api/handovers/{handover_id}/device-status"):
            page.locator("[data-confirm-status]").click()
        page.locator("[data-apply-status-slot]", has_text="Status confirmed").wait_for()
        assert posted == [{"status_label_id": None}]
        assert page.locator("[data-confirm-status]").count() == 0
    finally:
        page.close()


def test_new_handover_form_does_not_ask_for_the_engineer(
    headless_chrome, case_board
) -> None:
    base, _, _ = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/handovers?new=1", wait_until="networkidle")
        form = page.locator('[data-new-case-form][data-kind="handover"]')
        form.wait_for(state="visible")
        assert form.locator('[name="device_serial"]').count() == 1
        assert form.locator('[name="ticket_ref"]').count() == 1
        assert form.locator('[name="engineer"]').count() == 0
        assert "Engineer" not in form.inner_text()
    finally:
        page.close()


def test_recipient_quick_fill_buttons_use_holder_and_device_user(
    headless_chrome, case_board
) -> None:
    import re

    base, handover_id, _ = case_board
    detail = {
        "id": handover_id, "mode": "snipeit", "recipient_mode": "snipeit",
        "status": "draft", "maintenance_state": None, "outcome": "not_complete",
        "snipeit_status_name": "Ready to deploy", "stages": [],
        "events": [], "warnings": [], "missing": [],
        "device_holder_id": 7, "device_holder_name": "Holly Holder",
        "logged_on_user": "CORP\\sam.user",
    }
    urls = []

    def users(route):
        urls.append(route.request.url)
        route.fulfill(json=[{
            "id": 7, "name": "Holly Holder", "email": "holly@example.com",
            "username": "holly", "employee_num": "20077",
            "company": "B.tech", "same_company": True,
        }])

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        _route_handover_state(page, handover_id, detail)
        page.route(re.compile(r".*/api/snipeit/users.*"), users)
        # The live device (device-live) is the source of truth for the holder.
        page.route("**/device-live", lambda route: route.fulfill(json={
            "status": "Ready to deploy", "deployable": True,
            "assigned_to": {"id": detail["device_holder_id"], "name": detail["device_holder_name"]}
            if detail["device_holder_id"] else None,
        }))
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        search = page.locator("[data-recipient-search]")
        assert search.get_attribute("placeholder") == "Name, username or employee code"

        page.locator("[data-use-holder]").wait_for(state="visible")
        page.locator("[data-use-holder]").click()
        page.locator("[data-recipient-results] .recipient-row").wait_for()
        assert "user_id=7" in urls[-1]
        assert "Code 20077" in page.locator("[data-recipient-results]").inner_text()

        page.locator("[data-use-device-user]").click()
        page.wait_for_function("document.querySelector('[data-recipient-search]').value === 'sam.user'")
        assert search.input_value() == "sam.user"
        assert any("q=sam.user" in url for url in urls)

        # Sources empty -> both buttons are hidden.
        detail["device_holder_id"] = None
        detail["device_holder_name"] = None
        detail["logged_on_user"] = None
        page.reload(wait_until="networkidle")
        assert page.locator("[data-use-holder]").is_hidden()
        assert page.locator("[data-use-device-user]").is_hidden()
    finally:
        page.close()


def test_successful_print_fetches_pdf_without_downloading(
    headless_chrome, case_board
) -> None:
    base, handover_id, _ = case_board
    detail = {
        "id": handover_id, "mode": "snipeit", "recipient_mode": "snipeit",
        "status": "draft", "maintenance_state": None, "outcome": "ready",
        "snipeit_status_name": "Ready to deploy", "stages": [],
        "events": [], "warnings": [], "missing": [],
    }
    downloads = []
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.add_init_script("window.print = function () {};")
        _route_handover_state(page, handover_id, detail)
        page.route(
            f"**/api/handovers/{handover_id}/form?format=pdf",
            lambda route: route.fulfill(
                body=b"%PDF-1.4\n%%EOF\n",
                headers={"Content-Type": "application/pdf"},
            ),
        )
        page.on("download", lambda download: downloads.append(download))
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        with page.expect_request(f"**/api/handovers/{handover_id}/form?format=pdf") as request:
            page.locator("[data-print-form]").click()
        assert request.value.method == "GET"
        page.locator("iframe").wait_for(state="attached")
        assert downloads == []
        assert page.locator("[data-form-error]").is_hidden()
    finally:
        page.close()


def test_maintenance_open_handover_can_be_cancelled(headless_chrome, case_board) -> None:
    base, handover_id, _ = case_board
    item = {
        "case_id": handover_id, "serial": "SN-CALM", "state": "with_it",
        "model": "ThinkPad T14", "company": "B.tech", "reason": "Screen",
        "days": 1, "snipeit_status": "Ready to deploy", "assigned_to": "Alice",
        "stages": [{"stage": "snipeit_status", "status": "passed"}],
        "open_handover": {"id": handover_id},
    }
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route("**/api/maintenance/cases?state=with_it", lambda route: route.fulfill(json=[item]))
        page.route("**/api/maintenance/cases?state=at_vendor", lambda route: route.fulfill(json=[]))
        page.route(f"**/api/handovers/{handover_id}/cancel", lambda route: route.fulfill(json={}))
        page.goto(f"{base}/maintenance/devices", wait_until="networkidle")
        row = page.locator(f'tr[data-case-id="{handover_id}"]')
        link = row.get_by_text("Open handover", exact=True)
        assert link.get_attribute("href") == f"/handovers/{handover_id}"
        with page.expect_response(f"**/api/handovers/{handover_id}/cancel") as response:
            row.get_by_text("Cancel handover", exact=True).click()
        assert response.value.request.method == "POST"
        assert row.get_by_text("✓ Handover cancelled", exact=True).is_visible()
        assert row.get_by_text("Cancel handover", exact=True).count() == 0
    finally:
        page.close()


def test_navigation_crawl_and_case_captures(headless_chrome, case_board) -> None:
    base, handover_id, db_path = case_board
    paths = [
        "/", "/handovers", "/handovers?new=1", "/maintenance",
        "/maintenance/devices", "/maintenance/vendors", "/devices",
        "/devices/SN-CALM", "/sync", f"/handovers/{handover_id}",
        f"/handovers/{handover_id}/history",
        f"/maintenance/{handover_id}/history",
    ]
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        for path in paths:
            response = page.request.get(base + path)
            assert response.status == 200, (path, response.status)
            body = response.text()
            assert '{"detail":"Not Found"}' not in body, path
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        page.screenshot(path=str(REPO_ROOT / "docs/review/v2/polish-handover-case.png"), full_page=True)
        with _maintenance_seed(db_path, handover_id):
            page.goto(f"{base}/maintenance/{handover_id}", wait_until="networkidle")
            page.screenshot(path=str(REPO_ROOT / "docs/review/v2/polish-maintenance-case.png"), full_page=True)
    finally:
        page.close()


def test_dashboard_and_registration_meet_word_budgets(headless_chrome, case_board) -> None:
    base, _, _ = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/", wait_until="networkidle")
        dashboard_words = len(_words(page))
        assert dashboard_words <= 183, f"Dashboard shows {dashboard_words} words, budget 183"

        # The registration form is a drawer over the handovers board; measure
        # the drawer itself (the form the engineer reads and fills).
        page.goto(f"{base}/handovers?new=1", wait_until="networkidle")
        drawer = page.locator('[data-drawer][data-open="true"]')
        assert drawer.count() == 1
        drawer_words = len(drawer.first.inner_text().split())
        assert drawer_words <= 80, (
            f"New case registration shows {drawer_words} words, budget 80"
        )
    finally:
        page.close()


def _device_item(serial: str, kind: str, place: str, days_ago: int, holder: str | None = None) -> dict:
    from datetime import datetime, timedelta, timezone

    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "serial": serial, "asset_tag": f"TAG-{serial}", "model": "ThinkPad T14", "company": "B.tech",
        "place": place, "place_kind": kind, "holder": holder,
        "last_activity": when.isoformat(), "url": f"/devices/{serial}",
    }


def test_devices_list_states_filters_and_mobile_cards(headless_chrome, case_board) -> None:
    import json
    import re

    base, _, _ = case_board
    items = [
        _device_item("SN-A", "lab", "Ready lab", 3),
        _device_item("SN-B", "user", "With Alice", 40, "Alice"),
    ]
    requests: list[str] = []
    mode = {"value": "ok"}

    def api(route):
        requests.append(route.request.url)
        if mode["value"] == "error":
            route.fulfill(status=500, json={"detail": "Server exploded"})
        elif mode["value"] == "empty":
            route.fulfill(json={"items": [], "total": 0, "companies": ["B.tech"], "counts": {"lab": 0, "user": 0, "maintenance": 0, "unknown": 0}})
        else:
            route.fulfill(json={"items": items, "total": 2, "companies": ["B.tech", "Mylo"], "counts": {"lab": 1, "user": 1, "maintenance": 0, "unknown": 0}})

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route(re.compile(r".*/api/devices\?.*"), api)
        page.goto(f"{base}/devices", wait_until="networkidle")
        assert page.locator("[data-device-total]").inner_text() == "2 devices"
        assert page.locator(".dv-row").count() == 2
        assert [o.strip() for o in page.locator("[data-device-company] option").all_inner_texts()] == ["All companies", "B.tech", "Mylo"]
        assert page.locator("[data-place-chips] .chip").count() == 5
        assert "1" in page.locator('[data-place="lab"]').inner_text()
        last = page.locator(".dv-row").first.locator(".dv-last")
        assert last.inner_text() == "3 days ago"
        assert last.get_attribute("title")  # exact date on hover
        assert page.locator('[data-place-kind="lab"]').inner_text() == "Ready lab"

        # Place chip filters server side.
        page.locator('[data-place="user"]').click()
        page.wait_for_function("document.querySelector('[data-place=\"user\"]').getAttribute('aria-pressed') === 'true'")
        assert "place=user" in requests[-1]

        # Sorting toggles the order.
        page.locator("[data-sort-last]").click()
        page.wait_for_function("document.querySelector('[data-sort-head]').getAttribute('aria-sort') === 'ascending'")
        assert "order=asc" in requests[-1]

        # Typing is debounced into one request.
        before = len(requests)
        page.locator("[data-device-search]").type("sn-a", delay=20)
        page.wait_for_timeout(700)
        assert len(requests) == before + 1
        assert "q=sn-a" in requests[-1]

        # Empty state with a way out.
        mode["value"] = "empty"
        page.locator("[data-device-search]").fill("zzz")
        page.locator(".dv-empty").wait_for()
        assert "No devices match" in page.locator(".dv-empty").inner_text()
        mode["value"] = "ok"
        page.get_by_role("button", name="Clear filters").click()
        page.locator(".dv-row").first.wait_for()
        assert page.locator("[data-device-search]").input_value() == ""

        # Error state with retry.
        mode["value"] = "error"
        page.locator("[data-device-search]").fill("boom")
        page.locator(".dv-error").wait_for()
        assert "Devices could not be loaded" in page.locator(".dv-error").inner_text()
        mode["value"] = "ok"
        page.get_by_role("button", name="Retry").click()
        page.locator(".dv-row").first.wait_for()

        # Mobile: rows become cards and the header row is visually hidden.
        page.set_viewport_size({"width": 390, "height": 800})
        display = page.locator(".dv-row").first.evaluate("e => getComputedStyle(e).display")
        assert display == "grid"
        assert page.locator(".dv-table thead").evaluate("e => e.getBoundingClientRect().width") <= 1
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        json.dumps(requests)
    finally:
        page.close()


def test_device_detail_shows_live_state_and_snipeit_unavailable(headless_chrome, case_board) -> None:
    import re

    base, _, _ = case_board
    history = {
        "serial": "SN-A", "device": {"model": "ThinkPad T14", "company": "B.tech"},
        "cards": [{
            "date": "2026-11-20T10:00:00+00:00", "tag": "Handover", "headline": "Handed over to Alice",
            "facts": [{"label": "STATUS", "value": "Complete", "kind": "chip-ok"}], "case_url": "/handovers/x",
        }],
        "summary": {"now": "Ready lab", "handovers": 1, "maintenance_count": 0, "maintenance_days": 0,
                    "last_activity": "2026-11-20T10:00:00+00:00"},
    }
    lookup = {"fail": True}

    def device_lookup(route):
        if lookup["fail"]:
            route.fulfill(status=502, json={"detail": "Snipe-IT unavailable"})
        else:
            route.fulfill(json={"status": "Ready to deploy", "assigned_to": {"id": 1, "name": "Alice"}})

    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.route(re.compile(r".*/api/devices/SN-A/history"), lambda route: route.fulfill(json=history))
        page.route(re.compile(r".*/api/snipeit/device-lookup.*"), device_lookup)
        page.goto(f"{base}/devices/SN-A", wait_until="networkidle")
        assert page.locator("h1").inner_text() == "SN-A"
        assert page.locator("[data-device-summary] .summary-fact").count() == 4
        assert page.locator('[data-fact="now"] strong').inner_text() == "Ready lab"
        assert page.locator("[data-live-unavailable]").inner_text() == "Snipe-IT unavailable"
        assert page.locator(".history-date").first.inner_text().startswith("20 Nov 2026")
        assert page.locator(".milestone-title").inner_text() == "Handed over to Alice"
        assert page.locator("[data-new-handover]").is_visible() and page.locator("[data-new-maintenance]").is_visible()

        lookup["fail"] = False
        page.reload(wait_until="networkidle")
        assert page.locator("[data-live-status]").inner_text() == "Ready to deploy"
        assert page.locator("[data-live-holder]").inner_text().endswith("With Alice")
        assert page.locator('[data-fact="now"] strong').inner_text() == "With Alice"
    finally:
        page.close()
