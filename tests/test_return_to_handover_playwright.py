"""Regression test for the "Return to handover" button (visual prompt Part 4).

The alert card is a CSS grid with a zero-width first column.  A direct link
child therefore lands in that column and escapes the card, which is the broken
state the owner reported.  The link must sit in the content column, contain its
own label, stay inside the card and keep a whole-link focus ring at 1440 px and
390 px in both themes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

import pytest

playwright_sync = pytest.importorskip(
    "playwright.sync_api", reason="Playwright is not installed"
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8101
BASE_URL = f"http://127.0.0.1:{PORT}"

SERVER_ENV = {
    "SSO_ENABLED": "false",
    "SESSION_SECRET": "playwright-return-button",
    "HTTPS_ONLY": "false",
    "SNIPEIT_URL": "http://snipeit.test",
    "SNIPEIT_TOKEN": "",
    "APP_HOST": "",
}


@pytest.fixture(scope="module")
def portal():
    env = dict(os.environ)
    env.update(SERVER_ENV)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            time.sleep(1)
            try:
                with urllib.request.urlopen(
                    f"{BASE_URL}/api/health", timeout=3
                ) as response:
                    if response.status == 200:
                        break
            except Exception:
                pass
        else:
            raise RuntimeError("portal did not start")
        yield BASE_URL
    finally:
        proc.terminate()
        proc.wait(timeout=15)


@pytest.fixture(scope="module")
def browser():
    try:
        with playwright_sync.sync_playwright() as pw:
            launched = pw.chromium.launch()
            yield launched
            launched.close()
    except Exception as exc:  # browser binary missing in this environment
        pytest.skip(f"Chromium could not launch: {exc}")


def _contains(outer: dict, inner: dict, tolerance: float = 1.0) -> bool:
    return (
        inner["x"] >= outer["x"] - tolerance
        and inner["y"] >= outer["y"] - tolerance
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + tolerance
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + tolerance
    )


@pytest.mark.parametrize(
    ("width", "height", "theme"),
    [
        (1440, 900, "light"),
        (1440, 900, "dark"),
        (390, 844, "light"),
        (390, 844, "dark"),
    ],
)
def test_return_to_handover_link_is_inside_the_card(
    portal, browser, width, height, theme
):
    context = browser.new_context(
        viewport={"width": width, "height": height},
        color_scheme=theme,
    )
    page = context.new_page()
    try:
        page.goto(f"{portal}/?handover_id=test-handover", wait_until="load")
        link = page.get_by_role("link", name="Return to handover")
        link.wait_for(state="visible")

        link_box = link.bounding_box()
        # Measure the rendered text itself, not a particular child element, so
        # this also reproduces the old markup where the label was the anchor's
        # only child.
        label_box = link.evaluate(
            """el => {
                const range = document.createRange();
                range.selectNodeContents(el);
                const rect = range.getBoundingClientRect();
                return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            }"""
        )
        card = page.locator(".alert").first
        card_box = card.bounding_box()
        paragraph_box = card.locator(".alert-description").bounding_box()
        assert link_box and label_box and card_box and paragraph_box

        # The label is inside the link and the link is inside the card.
        assert _contains(link_box, label_box), (link_box, label_box)
        assert _contains(card_box, link_box), (card_box, link_box)

        # Non-zero size, in the content column, 16 px under the paragraph.
        assert link_box["width"] > 0 and link_box["height"] > 0
        assert abs(link_box["x"] - paragraph_box["x"]) <= 1, (
            link_box,
            paragraph_box,
        )
        assert link_box["y"] - (paragraph_box["y"] + paragraph_box["height"]) >= 15, (
            link_box,
            paragraph_box,
        )

        # The whole link, not a child, receives the focus ring.
        link.focus()
        shadow = link.evaluate(
            "el => getComputedStyle(el).boxShadow"
        )
        assert shadow and shadow != "none", shadow
        focused_box = link.bounding_box()
        assert focused_box == link_box

        # The theme actually applied; this is the condition the owner reported.
        is_dark = page.evaluate(
            "() => document.documentElement.classList.contains('dark')"
        )
        assert is_dark is (theme == "dark")
    finally:
        context.close()
