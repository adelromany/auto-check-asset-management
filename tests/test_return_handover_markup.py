"""Structural regression checks for the "return to case" action.

The device check now lives on /sync; when it is opened from a case the page
shows one banner with one button back to that case (the old /device-check
page had the same contract).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _alert_markup() -> str:
    template = (ROOT / "templates" / "sync.html").read_text(encoding="utf-8")
    start = template.index('<div class="alert alert-info" role="status">')
    end = template.index("{% endif %}", start)
    return template[start:end]


def test_return_to_handover_is_one_button_inside_alert_action_area() -> None:
    markup = _alert_markup()

    # The wording follows review B: the page is a device check for a case.
    assert "Device check for this handover" in markup
    # The action sits in its own grid-safe wrapper, never inline-styled.
    assert 'class="alert-actions"' in markup
    assert "width:" not in markup and "margin-left" not in markup
    # Exactly one button, and it says where it goes.
    assert markup.count("btn btn-outline btn-sm") == 1
    assert markup.index('<a href=') < markup.index("Return to case") < markup.index("</a>")
    assert 'aria-hidden="true"' in markup

    css = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".alert .alert-actions" in css and "col-start-2" in css
    assert ".alert .alert-body" in css


def test_unlinked_device_check_still_has_a_way_back_to_cases() -> None:
    """Without a case the banner is absent; the shell still links to cases."""
    template = (ROOT / "templates" / "sync.html").read_text(encoding="utf-8")
    assert "{% if back_to_case %}" in template

    rail = (ROOT / "templates" / "partials" / "rail.html").read_text(encoding="utf-8")
    bottom = (ROOT / "templates" / "partials" / "bottom_nav.html").read_text(encoding="utf-8")
    assert 'href="/handovers"' in rail
    assert 'href="/handovers"' in bottom

    css = (ROOT / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".btn:focus-visible" in css and "--tw-ring-shadow" in css
    assert ".btn-outline" in css and ".btn-sm" in css
