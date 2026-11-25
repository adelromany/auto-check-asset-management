"""Locate handover form templates by Snipe-IT company name."""

from __future__ import annotations

from pathlib import Path

from app.domain.company_rules import normalize_company


def find_template(forms_dir: Path, company: str | None) -> Path | None:
    """Return the DOCX template whose filename matches the company."""
    normalized = normalize_company(company)
    if not normalized:
        return None
    if not forms_dir.is_dir():
        return None
    for path in sorted(forms_dir.glob("*.docx")):
        if normalize_company(path.stem) == normalized:
            return path
    return None
