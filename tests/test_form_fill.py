"""Tests for filling the engineer placeholder in Word templates."""

from __future__ import annotations

import html
import zipfile
from io import BytesIO

import pytest

from pathlib import Path

from app.domain.form_fill import PLACEHOLDER, TemplateError, fill_engineer, fill_form


def _docx(document_xml: bytes, *, extra: dict[str, bytes] | None = None) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", b"content types")
        archive.writestr("word/document.xml", document_xml)
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    return output.getvalue()


def _document_text(content: bytes) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_fills_placeholder_in_one_run() -> None:
    template = _docx(
        b'<?xml version="1.0"?><w:document><w:body><w:p><w:r>'
        b"<w:t>Engineer: {{ENGINEER}}</w:t></w:r></w:p></w:body></w:document>"
    )

    result = fill_engineer(template, "Alex Engineer")

    assert "Alex Engineer" in _document_text(result)
    assert PLACEHOLDER not in _document_text(result)
    with zipfile.ZipFile(BytesIO(result)) as archive:
        assert archive.namelist()[0] == "[Content_Types].xml"
        assert archive.read("[Content_Types].xml") == b"content types"


def test_fills_placeholder_split_across_three_runs() -> None:
    template = _docx(
        b"<w:document><w:body><w:p>"
        b"<w:r><w:t>{{</w:t></w:r><w:r><w:t>ENGINEER</w:t></w:r>"
        b"<w:r><w:t>}}</w:t></w:r></w:p></w:body></w:document>"
    )

    result = fill_engineer(template, "Sam Engineer")

    text = _document_text(result)
    assert "Sam Engineer" in text
    assert "<w:t></w:t>" in text
    assert PLACEHOLDER not in text


def test_escapes_engineer_name() -> None:
    template = _docx(
        b"<w:document><w:body><w:p><w:r>"
        b"<w:t>{{ENGINEER}}</w:t></w:r></w:p></w:body></w:document>"
    )

    result = fill_engineer(template, 'A&B <"C">')

    assert 'A&B <"C">' in html.unescape(_document_text(result))


def test_raises_when_placeholder_is_missing() -> None:
    template = _docx(
        b"<w:document><w:body><w:p><w:r><w:t>No field</w:t></w:r></w:p></w:body></w:document>"
    )

    with pytest.raises(TemplateError, match="Placeholder .* not found"):
        fill_engineer(template, "Alex")


def test_fills_placeholder_in_header_and_footer() -> None:
    template = _docx(
        b"<w:document><w:body><w:p><w:r><w:t>Body</w:t></w:r></w:p></w:body></w:document>",
        extra={
            "word/header1.xml": b"<w:hdr><w:p><w:r><w:t>{{ENGINEER}}</w:t></w:r></w:p></w:hdr>",
            "word/footer1.xml": b"<w:ftr><w:p><w:r><w:t>{{ENGINEER}}</w:t></w:r></w:p></w:ftr>",
        },
    )

    result = fill_engineer(template, "Header Engineer")

    with zipfile.ZipFile(BytesIO(result)) as archive:
        assert "Header Engineer" in archive.read("word/header1.xml").decode()
        assert "Header Engineer" in archive.read("word/footer1.xml").decode()


def _cell(label: str) -> bytes:
    return f"<w:tc><w:p><w:r><w:t>{label}</w:t></w:r></w:p><w:p></w:p></w:tc>".encode()


def test_fills_inline_labels_split_over_runs_and_tables() -> None:
    template = _docx(
        b"<w:document><w:body><w:p><w:r><w:t>SN </w:t></w:r>"
        b"<w:r><w:t>:                         </w:t></w:r><w:r><w:t>Model : </w:t></w:r></w:p>"
        b"<w:tbl><w:tr>" + _cell("Model") + _cell("") + b"</w:tr>"
        b"<w:tr>" + _cell("Serial") + _cell("") + b"</w:tr>"
        b"<w:tr>" + _cell("Processor") + _cell("") + b"</w:tr></w:tbl>"
        b"<w:p><w:r><w:t>{{ENGINEER}}</w:t></w:r></w:p></w:body></w:document>"
    )
    result = fill_form(template, engineer="محمد", hardware={"model": "Dell Latitude 5440", "serial": "TEST-SN-0001", "processor": "Intel i5"})
    text = html.unescape(_document_text(result))
    assert "SN : TEST-SN-0001      Model : Dell Latitude 5440" in text
    assert "Intel i5" in text and "محمد" in text


def test_inline_missing_model_keeps_its_label() -> None:
    template = _docx(b"<w:document><w:p><w:r><w:t>{{ENGINEER}} SN : old Model : </w:t></w:r></w:p></w:document>")
    text = html.unescape(_document_text(fill_form(template, engineer="A", hardware={"serial": "NEW"})))
    assert "SN : NEW      Model :" in text


def test_real_templates_receive_hardware() -> None:
    hardware = {"processor": "Intel i5 (8 cores)", "ram": "16 GB", "disk": "512 GB SSD", "model": "Dell Latitude 5440", "serial": "TEST-SN-0001"}
    for name in ("B.tech.docx", "Mylo.docx"):
        source = Path("forms") / name
        text = html.unescape(_document_text(fill_form(source.read_bytes(), engineer="Alex", hardware=hardware)))
        assert hardware["serial"] in text and hardware["model"] in text
        assert hardware["processor"] in text and hardware["ram"] in text
