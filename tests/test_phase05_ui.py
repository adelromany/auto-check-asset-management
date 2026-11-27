"""Phase 05 server-rendered UI contracts."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_new_handover_drawer_requires_a_type_and_posts_on_start() -> None:
    script = (ROOT / "static" / "js" / "shell.js").read_text(encoding="utf-8")
    assert 'portal.formActions(isMaintenance ? "Register" : "Start")' in script
    assert script.count('data-new-mode", item.mode') == 1
    assert 'mode: "none", label: "Lab only"' in script
    assert 'mode: "snipeit", label: "Lab + user"' in script
    assert 'mode: "pending_user", label: "User not ready"' in script
    assert "actions.__primary.disabled = true" in script
    assert "payload.mode = selectedMode" in script


def test_dashboard_has_exactly_three_outcome_tiles() -> None:
    template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert template.count('class="tile kpi"') == 3
    assert 'data-kpi="ready"' in template
    assert 'data-kpi="complete"' in template
    assert 'data-kpi="not_complete"' in template
    for removed in ("waiting_user", "stalled", "warnings"):
        assert f'data-kpi="{removed}"' not in template


def test_case_page_has_three_independent_panels() -> None:
    template = (ROOT / "templates" / "handover_case.html").read_text(encoding="utf-8")
    for marker in ("data-status-select", "data-recipient-search", "data-print-form", "data-case-mode", "data-waiting-user-panel"):
        assert marker in template
    assert "data-recipient-none" not in template
    assert "data-recipient-external" not in template
