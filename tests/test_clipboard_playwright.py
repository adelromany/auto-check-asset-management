"""Clipboard condition-matrix tests (plan Phase 4).

Principle: do not test "on devices" — reproduce the CONDITIONS that make
devices differ (secure vs insecure origin, API present/removed/failing,
permission granted/denied) and assert every cell either copies or shows
the manual modal. A silent failure fails the test.

Matrix: browser {chromium, firefox, webkit} x origin {secure, insecure}.
Run: `python -m pytest tests/test_clipboard_playwright.py -q`
(Browsers must be installed: `python -m playwright install`.)

WebKit headless has known clipboard quirks on Linux; paste/read-back
assertions there are best-effort (xfail, non-strict, documented).
"""

import hashlib
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8099

SERVER_ENV = {
    "SSO_ENABLED": "false",
    "ENABLE_DIAG": "true",
    "SESSION_SECRET": "playwright-test",
    "HTTPS_ONLY": "false",
    "SESSION_TTL": "600",
    "AZURE_TENANT_ID": "test-tenant",
    "AZURE_CLIENT_ID": "test-id",
    "AZURE_CLIENT_SECRET": "test-secret",
    "REDIRECT_URI": "http://localhost:8099/auth/callback",
    "SNIPEIT_URL": "http://snipeit.test",
    "SNIPEIT_TOKEN": "",
    "APP_HOST": "",
}


def lan_ip():
    """Non-loopback LAN IP without sending any packet."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()


@pytest.fixture(scope="session")
def portal():
    env = dict(os.environ)
    env.update(SERVER_ENV)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=REPO_ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            time.sleep(1)
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{PORT}/api/health", timeout=3) as r:
                    if r.status == 200:
                        break
            except Exception:
                pass
        else:
            raise RuntimeError("portal did not start")
        yield {"secure": f"http://127.0.0.1:{PORT}",
               "insecure": f"http://{lan_ip()}:{PORT}"}
    finally:
        proc.terminate()
        proc.wait(timeout=15)


@pytest.fixture(params=["chromium", "firefox", "webkit"])
def target_browser(request):
    return request.param


@pytest.fixture()
def browser(target_browser):
    with sync_playwright() as pw:
        launched = getattr(pw, target_browser).launch()
        yield launched
        launched.close()


def open_portal(browser, url, **context_kwargs):
    ctx = browser.new_context(**context_kwargs)
    page = ctx.new_page()
    page.goto(url, wait_until="networkidle")
    page.wait_for_selector(".copy-btn", timeout=15000)
    return ctx, page


def first_command(page):
    return page.text_content(".cmd-body.active .cmd-pre")


def click_first_copy(page):
    page.click(".cmd-body.active .copy-btn")


def paste_into_fresh_textarea(page):
    """Paste via keyboard (needs no Clipboard API) and return the value."""
    page.evaluate("""() => {
        const ta = document.createElement('textarea');
        ta.id = 'pw-paste-target';
        document.body.appendChild(ta);
        ta.focus();
    }""")
    page.keyboard.press("Control+V")
    return page.eval_on_selector("#pw-paste-target", "el => el.value")


# ---------------------------------------------------------------------------
# 7.1 insecure origin reproduces the production condition (H1)
# ---------------------------------------------------------------------------

def test_insecure_origin_has_no_clipboard_api(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["insecure"])
    try:
        assert page.evaluate("window.isSecureContext") is False
        assert page.evaluate("typeof navigator.clipboard") == "undefined"
    finally:
        ctx.close()


def test_secure_origin_has_clipboard_api(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["secure"])
    try:
        assert page.evaluate("window.isSecureContext") is True
        assert page.evaluate("typeof navigator.clipboard") != "undefined"
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Copy on the insecure origin: success via tier 2, or manual modal. Never silent.
# ---------------------------------------------------------------------------

def test_copy_never_silent_on_insecure_origin(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["insecure"])
    try:
        click_first_copy(page)
        page.wait_for_timeout(800)
        label = page.text_content(".cmd-body.active .copy-btn")
        assert label != "Copy", "no visible feedback after click (silent failure)"
        modal = page.query_selector("#copy-manual-modal")
        if modal:
            assert "manually" in label.lower() or "manual" in page.content().lower()
        else:
            assert "copied" in label.lower(), f"unexpected feedback: {label!r}"
    finally:
        ctx.close()


def test_paste_integrity_on_insecure_origin(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["insecure"])
    try:
        expected = first_command(page)
        click_first_copy(page)
        page.wait_for_timeout(800)
        modal = page.query_selector("#copy-manual-modal")
        if modal:
            actual = page.eval_on_selector(
                "#copy-manual-modal textarea", "el => el.value")
        else:
            if target_browser == "webkit":
                pytest.xfail("webkit headless paste is best-effort")
            actual = paste_into_fresh_textarea(page)
        assert actual == expected, "pasted content differs from served command"
        assert (hashlib.sha256(actual.encode()).hexdigest()
                == hashlib.sha256(expected.encode()).hexdigest())
    finally:
        ctx.close()


def test_execcommand_cleanup_and_focus_restored(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["insecure"])
    try:
        click_first_copy(page)
        page.wait_for_timeout(800)
        if page.query_selector("#copy-manual-modal"):
            pytest.skip("tier 3 modal took over; nothing to clean up")
        assert page.evaluate(
            "document.querySelectorAll('body > textarea').length") == 0
        assert page.evaluate(
            "document.activeElement.tagName") in ("BODY", "BUTTON")
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Forced failures: stubbed API rejection + execCommand false => modal with text
# ---------------------------------------------------------------------------

def test_total_failure_shows_preselected_modal(portal, browser, target_browser):
    ctx = browser.new_context()
    ctx.add_init_script("""
        Object.defineProperty(Navigator.prototype, 'clipboard', {
            value: { writeText: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
            configurable: true,
        });
        document.execCommand = () => false;
    """)
    page = ctx.new_page()
    try:
        page.goto(portal["insecure"], wait_until="networkidle")
        page.wait_for_selector(".copy-btn", timeout=15000)
        expected = first_command(page)
        click_first_copy(page)
        page.wait_for_selector("#copy-manual-modal", timeout=8000)
        actual = page.eval_on_selector(
            "#copy-manual-modal textarea", "el => el.value")
        assert actual == expected
        assert page.eval_on_selector(
            "#copy-manual-modal textarea",
            "el => el.selectionStart === 0 && el.selectionEnd === el.value.length")
        page.click("#copy-manual-modal button:has-text('Close')")
        assert page.query_selector("#copy-manual-modal") is None
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Secure origin: tier 1 path end to end
# ---------------------------------------------------------------------------

def test_secure_origin_copies_via_clipboard_api(portal, browser, target_browser):
    kwargs = {}
    if target_browser == "chromium":
        kwargs["permissions"] = ["clipboard-read", "clipboard-write"]
    ctx, page = open_portal(browser, portal["secure"], **kwargs)
    try:
        expected = first_command(page)
        click_first_copy(page)
        page.wait_for_timeout(800)
        label = page.text_content(".cmd-body.active .copy-btn")
        assert "copied" in label.lower(), f"unexpected feedback: {label!r}"
        assert str(len(expected)) in label  # character count shown
        if target_browser == "chromium":
            assert page.evaluate("navigator.clipboard.readText()") == expected
        else:
            if target_browser == "webkit":
                pytest.xfail("webkit headless paste is best-effort")
            assert paste_into_fresh_textarea(page) == expected
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# 7.4 unit-level cases for copyText (method order, returns, cleanup)
# ---------------------------------------------------------------------------

STUBS = """
() => {
  window.__results = [];
  window.__execCalls = 0;
  const calls = [];
  Object.defineProperty(window, '__callLog', { value: calls, configurable: true });
  const origExec = document.execCommand.bind(document);
  document.execCommand = (...a) => { calls.push('exec'); return window.__execResult; };
  window.__setClipboard = (mode) => {
    if (mode === 'missing') {
      Object.defineProperty(Navigator.prototype, 'clipboard',
        { value: undefined, configurable: true });
    } else if (mode === 'reject') {
      Object.defineProperty(Navigator.prototype, 'clipboard', {
        value: { writeText: () => { calls.push('api'); return Promise.reject(new DOMException('x', 'NotAllowedError')); } },
        configurable: true });
    } else {
      Object.defineProperty(Navigator.prototype, 'clipboard', {
        value: { writeText: (t) => { calls.push('api'); window.__written = t; return Promise.resolve(); } },
        configurable: true });
    }
  };
  return true;
}
"""


def test_copytext_unit_matrix(portal, browser, target_browser):
    if target_browser != "chromium":
        pytest.skip("unit matrix runs once on chromium")
    ctx, page = open_portal(browser, portal["secure"])
    try:
        page.evaluate(STUBS)
        # (a) API succeeds -> tier 1, execCommand never called
        r = page.evaluate("""async () => {
            window.__setClipboard('ok'); window.__callLog.length = 0;
            const res = await copyText('hello');
            return { res, calls: [...window.__callLog], written: window.__written };
        }""")
        assert r["res"] == {"ok": True, "method": "clipboard-api"}
        assert r["calls"] == ["api"]
        assert r["written"] == "hello"

        # (b) API rejects -> tier 2
        r = page.evaluate("""async () => {
            window.__setClipboard('reject'); window.__callLog.length = 0;
            window.__execResult = true;
            const res = await copyText('hello');
            return { res, calls: [...window.__callLog] };
        }""")
        assert r["res"]["ok"] is True and r["res"]["method"] == "exec-command"
        assert r["calls"] == ["api", "exec"]

        # (c) API missing + exec false -> manual modal
        r = page.evaluate("""async () => {
            window.__setClipboard('missing'); window.__callLog.length = 0;
            window.__execResult = false;
            const res = await copyText('hello');
            return { res, calls: [...window.__callLog],
                     modal: !!document.getElementById('copy-manual-modal') };
        }""")
        assert r["res"]["ok"] is False and r["res"]["method"] == "manual"
        assert r["calls"] == ["exec"]
        assert r["modal"] is True
        page.click("#copy-manual-modal button:has-text('Close')")

        # (d) execCommand throws -> manual
        r = page.evaluate("""async () => {
            window.__setClipboard('missing');
            document.execCommand = () => { throw new DOMException('x', 'InvalidStateError'); };
            const res = await copyText('hello');
            return { res, modal: !!document.getElementById('copy-manual-modal') };
        }""")
        assert r["res"]["method"] == "manual" and r["modal"] is True
        page.click("#copy-manual-modal button:has-text('Close')")

        # cleanup: no leftover helper nodes
        assert page.evaluate(
            "document.querySelectorAll('body > textarea').length") == 0
        assert page.query_selector("#copy-manual-modal") is None
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Diagnostics page loads in a real browser
# ---------------------------------------------------------------------------

def test_diag_page_loads(portal, browser, target_browser):
    ctx, page = open_portal(browser, portal["secure"])
    try:
        page.goto(portal["secure"] + "/diag/clipboard")
        for marker in ("isSecureContext", "Method A", "paste-target"):
            assert marker in page.content(), marker
    finally:
        ctx.close()
