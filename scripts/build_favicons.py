"""Generate the favicon PNGs from the b_labs JPEG.

The mark must never be cropped: it is placed whole (object-fit: contain) on
an ink (#1A1A1A) chip with rounded corners, exactly like the in-app logo.

Build:  python scripts/build_favicons.py
Output: static/img/favicon-32.png, static/img/favicon-180.png

Uses Playwright, which is already a repository dependency; no network.
"""

from __future__ import annotations

import base64
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JPEG = REPO_ROOT / "static" / "img" / "b_labs.jpeg"
OUTPUTS = {
    32: REPO_ROOT / "static" / "img" / "favicon-32.png",
    180: REPO_ROOT / "static" / "img" / "favicon-180.png",
}

HTML = """<!doctype html><html><body style="margin:0">
<div id="chip" style="width:{size}px;height:{size}px;background:#1A1A1A;
  border-radius:{radius}px;display:flex;align-items:center;justify-content:center;
  box-sizing:border-box;padding:{pad}px">
  <img src="data:image/jpeg;base64,{data}" style="width:100%;height:100%;
    object-fit:contain;display:block;border-radius:{inner}px">
</div>
</body></html>"""


def build() -> None:
    from playwright.sync_api import sync_playwright

    data = base64.b64encode(JPEG.read_bytes()).decode("ascii")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for size, target in OUTPUTS.items():
                pad = max(2, size // 12)
                radius = max(6, size // 4)
                page = browser.new_page(
                    viewport={"width": size, "height": size},
                    device_scale_factor=2,
                )
                page.set_content(
                    HTML.format(
                        size=size,
                        data=data,
                        pad=pad,
                        radius=radius,
                        inner=max(3, radius - pad // 2),
                    )
                )
                page.locator("#chip").screenshot(path=str(target))
                page.close()
        finally:
            browser.close()
    for size, target in OUTPUTS.items():
        print(f"wrote {target} ({size}x{size})")


if __name__ == "__main__":
    build()
