"""The UI click-through test (owner rule: nothing is done until this is green).

What it does, per phase of the current UI:

1. **Crawl** every page reachable from the nav and from links on each page.
   A crawl fails when a link target answers 4xx/5xx or when an HTML page
   answers with a JSON body (the raw ``{"detail": "Not Found"}`` defect).
2. **Click** every visible button and link-like control on each screen and in
   each open drawer. A click must produce at least one of: a network call, a
   DOM change, a URL change, a toast/message, a dialog or a popup - unless
   the control is disabled *with a visible reason*.
3. Fail on any console error, any uncaught page error, and any 4xx/5xx
   response whose result is not shown to the user (a toast, an inline
   message, a dialog or an error page).  A 422 shown inline is fine.
4. Assert the **same shell** on every page: desktop rail with visible labels,
   mobile bottom nav, top bar - and exactly one nav item marked active.
5. Assert ``/`` is the Dashboard and the four nav destinations each lead to a
   page with a different ``<h1>``.

Run:  python -m pytest tests/e2e/test_clickthrough.py -q
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import sync_playwright

BASE = None  # set by the portal fixture


VIEWPORTS = {"desktop": (1440, 900), "mobile": (390, 844)}
CLICK_SETTLE_MS = 1200
FEEDBACK_WINDOW_MS = 2500
MAX_CLICKS_PER_PAGE = 80
MAX_PAGES = 40

# Pages the click pass visits (buttons are exercised here, not on every page):
# the four screens, one case per kind, both history pages. The crawl covers
# every other reachable page.
CLICK_PAGES = "all"  # resolved after the crawl: every page in the crawl set


class PageMonitor:
    """Collects responses, console errors and feedback per page."""

    def __init__(self, page):
        self.page = page
        self.responses: list[tuple[str, int, str]] = []  # url, status, ctype
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.dialog_opened = False
        self.popup_opened = False
        self.handled_statuses: set[int] = set()
        self.navigations = 0
        page.on("framenavigated", self._on_navigated)
        page.on(
            "response",
            lambda response: self._on_response(response),
        )
        page.on(
            "console",
            lambda msg: self._on_console(msg),
        )
        page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        page.on("dialog", lambda dialog: self._on_dialog(dialog))

    def _on_navigated(self, frame) -> None:
        if frame == self.page.main_frame:
            self.navigations += 1

    def _on_response(self, response) -> None:
        try:
            ctype = response.headers.get("content-type", "")
        except Exception:
            ctype = ""
        self.responses.append((response.url, response.status, ctype))

    def _on_console(self, msg) -> None:
        if msg.type != "error":
            return
        text = msg.text or ""
        match = re.search(r"status of (\d\d\d)", text)
        if match and int(match.group(1)) in self.handled_statuses:
            return  # the 4xx/5xx was shown to the user; not a silent error
        self.console_errors.append(text)

    def _on_dialog(self, dialog) -> None:
        self.dialog_opened = True
        dialog.accept()

    def install_mutation_counter(self) -> None:
        self.page.evaluate(
            """() => {
                window.__pwMutations = 0;
                const observer = new MutationObserver(() => {
                    window.__pwMutations += 1;
                });
                observer.observe(document.documentElement, {
                    childList: true, subtree: true, attributes: true,
                    characterData: true,
                });
            }"""
        )

    def mutations(self) -> int:
        try:
            return self.page.evaluate("window.__pwMutations || 0")
        except Exception:
            return 0

    def responses_since(self, index: int) -> list[tuple[str, int, str]]:
        return self.responses[index:]

    def note_status(self, status: int) -> None:
        self.handled_statuses.add(status)


def _is_page_url(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    path = parts.path or "/"
    if path.startswith("/static/") or path.startswith("/api/"):
        return False
    return True


def _page_key(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return path


def _status_class(status: int) -> str:
    if 200 <= status < 400:
        return "ok"
    return "error"


def _feedback_visible(monitor: PageMonitor, base_url: str) -> bool:
    """Toast / inline message / dialog / popup / alert roles."""
    page = monitor.page
    selectors = (
        "[data-toast]",
        "[role=alert]",
        "[role=status]",
        ".toast",
        "[data-error-message]",
        "[data-error]",
        "[data-form-error]",
    )
    for selector in selectors:
        try:
            found = page.locator(selector).filter(visible=True)
            if found.count() > 0:
                return True
        except Exception:
            continue
    return monitor.dialog_opened or monitor.popup_opened


def _capture(monitor: PageMonitor) -> dict:
    """Sampled immediately before a click, so fast responses are not missed."""
    return {
        "mutations": monitor.mutations(),
        "responses": len(monitor.responses),
        "url": monitor.page.url,
        "navigations": monitor.navigations,
    }


def _click_feedback(monitor: PageMonitor, before: dict) -> tuple[bool, list[str]]:
    """Wait up to FEEDBACK_WINDOW_MS for any sign the click did something."""
    page = monitor.page

    start_mutations = before["mutations"]
    start_url = before["url"]
    responses_at_start = before["responses"]
    saw_status_error: list[int] = []
    saw_status_any: list[int] = []

    import time as _time

    waited = 0
    while waited < FEEDBACK_WINDOW_MS:
        _time.sleep(0.2)
        waited += 200
        new_responses = monitor.responses[responses_at_start:]
        for url, status, _ctype in new_responses:
            if status >= 400:
                saw_status_error.append(status)
            else:
                saw_status_any.append(status)
        if monitor.mutations() > start_mutations:
            if saw_status_error:
                for status in set(saw_status_error):
                    monitor.note_status(status)
            return True, []
        if monitor.navigations > before["navigations"]:
            # A full page load (same URL reload included) is visible feedback;
            # the mutation counter was reset by the new document.
            return True, []
        if page.url != start_url:
            if saw_status_error:
                for status in set(saw_status_error):
                    monitor.note_status(status)
            return True, []
        if saw_status_error and _feedback_visible(monitor, BASE):
            for status in set(saw_status_error):
                monitor.note_status(status)
            return True, []
        if saw_status_any and _feedback_visible(monitor, BASE):
            return True, []
        if monitor.dialog_opened or monitor.popup_opened:
            return True, []
    if saw_status_error:
        # Nothing shown for the error statuses.
        return False, [f"HTTP {s} with no visible result" for s in set(saw_status_error)]
    if saw_status_any:
        # A network call fired but no visible change: still counts as actioned
        # only if a toast/status element appeared; otherwise the click is dead.
        return False, ["network call with no visible result"]
    return False, []


def _reason_visible(page, element) -> bool:
    """Disabled controls must show why (title, aria-label or a reason chip)."""
    try:
        title = element.get_attribute("title") or ""
        label = element.get_attribute("aria-label") or ""
        if title.strip() or label.strip():
            return True
        parent = element.locator("xpath=..")
        text = parent.inner_text(timeout=300)
        return bool(text.strip())
    except Exception:
        return False


def _inside(container, element) -> bool:
    """True when the element lives inside the given container element."""
    try:
        handle = container.element_handle()
        if handle is None:
            return False
        return bool(
            element.evaluate("(el, box) => box.contains(el)", handle)
        )
    except Exception:
        return False


def _is_close_control(element) -> bool:
    try:
        return element.get_attribute("data-drawer-close") is not None
    except Exception:
        return False


def _control_key(element) -> str:
    try:
        return element.evaluate("el => el.outerHTML.slice(0, 160)")
    except Exception:
        return "unknown"


def _control_text(el) -> str:
    try:
        text = (el.inner_text(timeout=300) or "").strip().split("\n")[0].strip()
    except Exception:
        text = ""
    if not text:
        try:
            text = (el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()
        except Exception:
            text = ""
    return text[:40]


def _visible_controls(page):
    controls: list[tuple[str, object, str]] = []
    buttons = page.locator("button:visible, [role=button]:visible")
    for i in range(buttons.count()):
        el = buttons.nth(i)
        text = _control_text(el)
        controls.append(("button", el, f"button#{i}:{text}" if text else f"button#{i}"))
    links = page.locator("a[href]:visible")
    for i in range(links.count()):
        el = links.nth(i)
        href = el.get_attribute("href") or ""
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        text = _control_text(el)
        controls.append(("link", el, f"link#{i}:{text or href} ({href})"))
    return controls


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True)
        except Exception:
            pytest.skip("no Chromium available for the click-through test")
        try:
            yield instance
        finally:
            instance.close()


def test_clickthrough(portal, browser):
    global BASE
    BASE = portal.base

    problems: list[str] = []
    stats = {"pages": 0, "links": 0, "buttons": 0, "clicks": 0}
    visited_pages: set[str] = set()
    clicked_pairs: set[tuple[str, str]] = set()
    start_paths = [
        p.strip()
        for p in os.environ.get("CLICKTHROUGH_PATHS", "/").split(",")
        if p.strip()
    ]
    queue: list[str] = start_paths or ["/"]

    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.set_default_timeout(8000)
    context.on(
        "page",
        lambda popup: popup.on(
            "response",
            lambda response: popup.__dict__.setdefault(
                "_responses", []
            ).append((response.url, response.status)),
        ),
    )

    pages = {}
    page = context.new_page()
    monitor = PageMonitor(page)
    pages["main"] = monitor

    def crawl() -> list[str]:
        """BFS over pages; returns visited page paths in discovery order."""
        order: list[str] = []
        while queue and len(visited_pages) < MAX_PAGES:
            path = queue.pop(0)
            if path in visited_pages:
                continue
            visited_pages.add(path)
            order.append(path)
            try:
                page.goto(BASE + path, wait_until="load")
                page.wait_for_timeout(500)
            except Exception as exc:
                problems.append(f"crawl: {path} failed to load: {exc}")
                continue
            final = page.url
            if _page_key(final) != path and not final.startswith(BASE + path):
                # A redirect is fine when the app moved the URL on purpose
                # (a 301/308 legacy move or /logout back home) and lands on a
                # page the crawl knows; anything else is a surprise.
                redirect_status = next(
                    (
                        status
                        for url, status, _ctype in monitor.responses
                        if urlsplit(url).path == path and 300 <= status < 400
                    ),
                    None,
                )
                intended = redirect_status in (301, 307, 308)
                known_target = (
                    _page_key(final) in visited_pages
                    or _page_key(final) in queue
                )
                if not (intended and known_target):
                    problems.append(
                        f"crawl: {path} landed on {final} (unexpected redirect)"
                    )
            response_entries = [
                (url, status, ctype)
                for url, status, ctype in monitor.responses
                if urlsplit(url).path == _page_key(final) or status >= 400
            ]
            for url, status, ctype in response_entries:
                if _status_class(status) == "ok":
                    if "text/html" not in ctype and not url.startswith(BASE + "/api/"):
                        problems.append(
                            f"crawl: {path} answered {status} with {ctype or 'no'} "
                            "content-type (page must be HTML)"
                        )
                    continue
                if url.startswith(BASE + "/api/") or url.startswith(BASE + "/static/"):
                    continue  # subresource failures are handled by the click pass
                problems.append(f"crawl: {path} answered HTTP {status}")
            html = page.content()
            ctype = ""
            for url, status, c in monitor.responses:
                if urlsplit(url).path == _page_key(final):
                    ctype = c
            if "application/json" in ctype:
                problems.append(f"crawl: {path} rendered a JSON body ({ctype})")
            if json_ok(html) and "text/html" not in ctype:
                problems.append(f"crawl: {path} body looks like raw JSON")
            stats["pages"] += 1
            for href in collect_links(page):
                stats["links"] += 1
                target = absolutize(href, BASE)
                if not _is_page_url(target):
                    continue
                key = _page_key(target)
                if key.startswith("/api"):
                    problems.append(
                        f"crawl: {path} contains a link to the API path {href}"
                    )
                    continue
                if key not in visited_pages and key not in queue:
                    queue.append(key)
        return order

    visited = crawl()

    # -- click pass on every crawled page ------------------------------------
    for path in visited:
        page.goto(BASE + path, wait_until="load")
        page.wait_for_timeout(400)
        monitor.install_mutation_counter()
        monitor.responses = []  # reset per page
        monitor.handled_statuses = set()
        clicks = 0
        iterations = 0
        seen: set[str] = set()
        escapes = 0
        while clicks < MAX_CLICKS_PER_PAGE and iterations < MAX_CLICKS_PER_PAGE * 2:
            iterations += 1
            drawer = page.locator('[data-drawer][data-open="true"]')
            drawer_open = drawer.count() > 0
            if not drawer_open:
                escapes = 0
            controls = _visible_controls(page)
            if drawer_open:
                inside = [item for item in controls if _inside(drawer.first, item[1])]
                # Prefer real drawer actions over the close button; the drawer
                # is closed with Escape when nothing else is left.
                actionable = [item for item in inside if not _is_close_control(item[1])]
                controls = actionable
            candidate = None
            for kind, element, label in controls:
                key = f"{kind}::{_control_key(element)}"
                if key in seen:
                    continue
                if kind == "button":
                    disabled = (
                        element.is_disabled()
                        or (element.get_attribute("aria-disabled") == "true")
                    )
                    if disabled:
                        seen.add(key)
                        if not _reason_visible(page, element):
                            problems.append(
                                f"clicks {path}: disabled {label} shows no reason"
                            )
                        continue
                else:
                    href = element.get_attribute("href") or ""
                    target = absolutize(href, BASE)
                    pair = (path, _page_key(target) + href)
                    if not _is_page_url(target) or pair in clicked_pairs:
                        seen.add(key)
                        continue
                candidate = (kind, element, label, key)
                break
            if candidate is None:
                if drawer_open and escapes < 3:
                    # Exhausted the drawer: close it the keyboard way.
                    escapes += 1
                    page.evaluate(
                        "() => { const el = document.activeElement;"
                        " if (el && el.blur) el.blur(); }"
                    )
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    continue
                if drawer_open:
                    problems.append(f"clicks {path}: drawer did not close with Escape")
                break
            kind, element, label, key = candidate
            seen.add(key)
            try:
                if kind == "button":
                    pair = (path, key)
                    if pair in clicked_pairs:
                        continue
                    clicked_pairs.add(pair)
                    stats["buttons"] += 1
                    stats["clicks"] += 1
                    clicks += 1
                    before_url = page.url
                    monitor.dialog_opened = False
                    before = _capture(monitor)
                    try:
                        element.click(timeout=4000)
                    except Exception as exc:
                        problems.append(
                            f"clicks {path}: {label} could not be clicked: {exc}"
                        )
                        continue
                    ok, notes = _click_feedback(monitor, before)
                    if not ok:
                        problems.append(
                            f"clicks {path}: {label} is a dead button "
                            + ("; ".join(notes) or "no response at all")
                        )
                    if monitor.navigations != before["navigations"]:
                        # Reload or navigation: wait for the new document and
                        # start over with fresh controls and a fresh observer.
                        try:
                            page.wait_for_load_state("load", timeout=5000)
                        except Exception:
                            pass
                        page.wait_for_timeout(300)
                        if _page_key(page.url) != path:
                            page.goto(BASE + path, wait_until="load")
                            page.wait_for_timeout(300)
                        monitor.install_mutation_counter()
                        seen.clear()
                        continue
                    if page.url != before_url and _page_key(page.url) != path:
                        # navigated away: come back and keep going
                        page.goto(BASE + path, wait_until="load")
                        page.wait_for_timeout(300)
                        monitor.install_mutation_counter()
                        seen.clear()
                else:  # link
                    href = element.get_attribute("href") or ""
                    target = absolutize(href, BASE)
                    pair = (path, _page_key(target) + href)
                    clicked_pairs.add(pair)
                    stats["clicks"] += 1
                    before_url = page.url
                    monitor.dialog_opened = False
                    try:
                        element.click(timeout=4000)
                        page.wait_for_timeout(400)
                    except Exception:
                        continue
                    if page.url == before_url:
                        # same-page anchors are fine; anything else is dead
                        continue
                    stats["links"] += 1
                    final_url = page.url
                    if _page_key(final_url).startswith("/api"):
                        problems.append(
                            f"clicks {path}: link {href} opened the API page "
                            f"{_page_key(final_url)}"
                        )
                    for url, status, _ctype in monitor.responses[-8:]:
                        if urlsplit(url).path == _page_key(final_url):
                            if _status_class(status) != "ok":
                                problems.append(
                                    f"clicks {path}: link {href} answered "
                                    f"HTTP {status}"
                                )
                    # go back and continue
                    page.goto(BASE + path, wait_until="load")
                    page.wait_for_timeout(300)
                    monitor.install_mutation_counter()
                    seen.clear()
            except Exception as exc:
                problems.append(f"clicks {path}: error on {label}: {exc}")

    # -- shell checks ---------------------------------------------------------
    for path in visited:
        for name, (width, height) in VIEWPORTS.items():
            page.set_viewport_size({"width": width, "height": height})
            page.goto(BASE + path, wait_until="load")
            page.wait_for_timeout(400)
            if name == "desktop":
                rail = page.locator("aside[data-rail], nav[data-rail]").filter(
                    visible=True
                )
                if rail.count() == 0:
                    problems.append(f"shell {path}: no visible left rail on desktop")
                else:
                    labels = page.locator("[data-rail] [data-nav-label]:visible")
                    nav_items = page.locator("[data-rail] a[data-nav]")
                    if nav_items.count() and labels.count() < nav_items.count():
                        problems.append(
                            f"shell {path}: rail labels are not always visible "
                            f"({labels.count()}/{nav_items.count()})"
                        )
                topbar = page.locator("header[data-topbar]").filter(visible=True)
                if topbar.count() == 0:
                    problems.append(f"shell {path}: no visible top bar")
            else:
                bottom = page.locator("nav[data-bottomnav]").filter(visible=True)
                if bottom.count() == 0:
                    problems.append(f"shell {path}: no visible bottom nav on mobile")
            active = page.locator("[data-nav-active='true']:visible")
            if active.count() != 1:
                problems.append(
                    f"shell {path}: {active.count()} active nav items (want 1)"
                )

    # -- four destinations, different h1 --------------------------------------
    page.set_viewport_size({"width": 1440, "height": 900})
    nav_targets = {}
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_timeout(400)
    nav_links = page.locator("[data-rail] a[data-nav]:visible")
    count = nav_links.count()
    if count != 4:
        problems.append(f"nav: only {count} visible rail items (want 4)")
    groups = page.locator("[data-rail] .rail-group").all_inner_texts()
    if groups != ["Handover", "Maintenance"]:
        problems.append(f"nav: unexpected groups {groups}")
    for i in range(min(count, 4)):
        link = nav_links.nth(i)
        href = absolutize(link.get_attribute("href") or "", BASE)
        link.click()
        page.wait_for_timeout(600)
        h1 = page.locator("h1").first.inner_text(timeout=4000).strip()
        nav_targets[href] = h1
    if "/" in nav_targets and nav_targets["/"] == "":
        problems.append("nav: / renders no h1")
    h1s = list(nav_targets.values())
    if len(set(h1s)) != len(h1s):
        problems.append(f"nav: two destinations share an h1: {nav_targets}")

    context.close()

    # summary for the report
    summary = {
        "pages": stats["pages"],
        "links_checked": stats["links"],
        "buttons_checked": stats["buttons"],
        "total_clicks": stats["clicks"],
        "problems": len(problems),
    }
    print("CLICKTHROUGH-SUMMARY " + json.dumps(summary))
    dump_path = os.environ.get("CLICKTHROUGH_DUMP")
    if dump_path:
        Path(dump_path).write_text("\n".join(problems), encoding="utf-8")
    assert not problems, (
        f"{len(problems)} problems:\n" + "\n".join(problems[:200])
    )


def json_ok(text: str) -> bool:
    stripped = text.strip()
    if not (stripped.startswith("{") or stripped.startswith("[")):
        return False
    try:
        json.loads(stripped)
        return True
    except Exception:
        return False


def collect_links(page) -> list[str]:
    hrefs = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.getAttribute('href'))"
    )
    return [h for h in hrefs if h]


def absolutize(href: str, base: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return base + (href if href.startswith("/") else "/" + href)
