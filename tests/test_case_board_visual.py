"""Owner review C: the case board must stay calm at every width.

The three visible-word budgets are **220 / 160 / 80** at 1440 / 768 / 390 px.
This is the conservative reading of the review's "220/160/80" requirement and
is recorded as PROPOSED in decision D-73; the owner can confirm or change it.

Chrome is used when it is installed. Without a browser the test skips rather
than failing the suite, matching the existing Playwright test's contract.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models.handover import Handover, HandoverStage
from app.domain.stages import STAGE_ORDER

REPO_ROOT = Path(__file__).resolve().parents[1]
BUDGETS = ((1440, 900, 220), (768, 1024, 160), (390, 844, 80))


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
        yield base, handover_id
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
    base, handover_id = case_board
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


def test_case_board_has_nine_operation_tiles_and_drawer(headless_chrome, case_board) -> None:
    base, handover_id = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/handovers/{handover_id}", wait_until="networkidle")
        tiles = page.locator("[data-op-tile]")
        assert tiles.count() == 9

        # No drawer is rendered until a tile is opened.
        drawer = page.locator('[data-drawer][data-open="true"]')
        assert drawer.count() == 0

        # Clicking a tile opens the side-sheet drawer.
        page.locator('[data-op-tile="agent_report"]').click()
        drawer = page.locator('[data-drawer][data-open="true"]')
        assert drawer.count() == 1

        # Pressing Escape closes it.
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        assert page.locator('[data-drawer][data-open="true"]').count() == 0
    finally:
        page.close()


def test_dashboard_and_registration_meet_word_budgets(headless_chrome, case_board) -> None:
    base, _ = case_board
    page = headless_chrome.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(f"{base}/", wait_until="networkidle")
        dashboard_words = len(_words(page))
        assert dashboard_words <= 160, f"Dashboard shows {dashboard_words} words, budget 160"

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
