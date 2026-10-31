"""Structural regression checks for the handover return action."""

from pathlib import Path


def test_return_to_handover_is_one_button_inside_alert_action_area() -> None:
    template = (Path(__file__).resolve().parents[1] / "templates" / "index.html").read_text(encoding="utf-8")
    start = template.index('<div class="alert alert-info mb-4" role="status">')
    end = template.index("{% else %}", start)
    markup = template[start:end]

    assert 'Device check for this handover' in markup
    assert 'class="col-start-2 mt-4"' in markup
    assert 'class="btn btn-outline btn-sm"' in markup
    assert markup.index('<a class="btn btn-outline btn-sm"') < markup.index("Return to handover") < markup.index("</a>")
    assert 'aria-hidden="true"' in markup
    assert "width:" not in markup and "margin-left" not in markup
    assert "mt-4" in template and "col-start-2" in template

    css = (Path(__file__).resolve().parents[1] / "static/css/app.css").read_text(encoding="utf-8")
    assert ".btn:focus-visible" in css and "--tw-ring-shadow" in css
    assert ".btn-outline" in css and ".btn-sm" in css


def test_unlinked_handover_action_uses_the_same_grid_safe_wrapper() -> None:
    template = (Path(__file__).resolve().parents[1] / "templates" / "index.html").read_text(encoding="utf-8")
    section = template.split("{% else %}", 1)[1].split("{% endif %}", 1)[0]
    assert 'class="col-start-2 mt-4"' in section
    assert 'class="btn btn-outline btn-sm"' in section
    assert section.index('<a class="btn btn-outline btn-sm"') < section.index("Open handover cases") < section.index("</a>")
