"""Tests for the clipboard diagnostics page (flag-gated, offline)."""


def test_diag_disabled_by_default(make_client):
    client, _ = make_client()
    assert client.get("/diag/clipboard").status_code == 404
    r = client.post("/diag/clipboard/report", json={"isSecureContext": True})
    assert r.status_code == 404


def test_diag_page_when_enabled(make_client):
    client, _ = make_client(ENABLE_DIAG="true")
    r = client.get("/diag/clipboard")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    for marker in ("isSecureContext", "Method A", "Method B", "paste-target",
                   "clipboard-probe", "/diag/clipboard/report"):
        assert marker in r.text, marker


def test_diag_report_accepted_when_enabled(make_client):
    client, _ = make_client(ENABLE_DIAG="true")
    payload = {"isSecureContext": False, "protocol": "http:",
               "host": "192.168.1.50:8080", "clipboardType": "undefined",
               "methodA": {"ok": False}, "methodB": {"ok": True},
               "userAgent": "UA", "platform": "Win32", "extra": "dropped"}
    r = client.post("/diag/clipboard/report", json=payload)
    assert r.status_code == 200
    assert r.json() == {"logged": True}


def test_diag_report_rejects_bad_json_when_enabled(make_client):
    client, _ = make_client(ENABLE_DIAG="true")
    r = client.post("/diag/clipboard/report", content="not-json",
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 400
