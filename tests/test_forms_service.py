"""Tests for company-based handover template lookup."""

from pathlib import Path

from app.services.forms import find_template


def _template(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_bytes(b"docx")
    return path


def test_btech_matches_btech_template(tmp_path: Path) -> None:
    template = _template(tmp_path, "B.tech.docx")

    assert find_template(tmp_path, "B.tech") == template


def test_normalized_company_matches_template(tmp_path: Path) -> None:
    template = _template(tmp_path, "B.tech.docx")

    assert find_template(tmp_path, "btech") == template


def test_unknown_company_returns_none(tmp_path: Path) -> None:
    _template(tmp_path, "B.tech.docx")

    assert find_template(tmp_path, "Unknown") is None
    assert find_template(tmp_path, None) is None
