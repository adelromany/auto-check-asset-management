"""Browser contract for the three-state handover UI."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_dashboard_and_handover_filter_have_only_outcomes(tmp_path: Path) -> None:
    port = _port()
    env = dict(os.environ)
    env.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{(tmp_path / 'ui.db').as_posix()}",
        SSO_ENABLED="false",
        SESSION_SECRET="p1-ui-test",
        HTTPS_ONLY="false",
        SNIPEIT_URL="http://127.0.0.1:9",
        SNIPEIT_TOKEN="",
        DOCUMENTS_DIR=str(tmp_path / "documents"),
    )
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        timeout=60,
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(80):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.1)
        else:
            pytest.fail("UI test portal did not start")
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=True)
            except Exception as exc:
                pytest.skip(f"Chromium is unavailable: {exc}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(base + "/", wait_until="networkidle")
                assert page.locator("[data-kpi]").count() == 3
                assert [" ".join(text.split()) for text in page.locator("[data-kpi]").all_text_contents()] == [
                    "0 Ready labs",
                    "0 Complete",
                    "0 Not complete",
                ]
                page.goto(base + "/handovers", wait_until="networkidle")
                assert page.locator("#handover-outcome option").all_inner_texts() == [
                    "All",
                    "Ready lab",
                    "Complete",
                    "Not complete",
                ]
                page.goto(base + "/", wait_until="networkidle")
                output = ROOT / "docs" / "review" / "v2" / "p1-dashboard.png"
                output.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(output), full_page=True)
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
