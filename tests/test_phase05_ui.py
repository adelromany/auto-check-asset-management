"""Phase 05 server-rendered UI contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_handover_drawer_is_serial_only_and_posts_on_start() -> None:
    script = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert 'portal.drawerForm("New handover"' in script
    assert 'portal.field("Serial", input)' in script
    assert 'portal.apiJson("/api/handovers"' in script
    assert 'portal.formActions("Start")' in script


def test_case_page_has_three_independent_panels() -> None:
    template = (ROOT / "templates" / "handover_case.html").read_text(encoding="utf-8")
    for marker in ("data-status-select", "data-recipient-search", "data-print-form"):
        assert marker in template
