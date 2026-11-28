"""Fill engineer and hardware fields in Word handover templates."""

from __future__ import annotations

import html
import re
import zipfile
from io import BytesIO
from xml.sax.saxutils import escape

PLACEHOLDER = "{{ENGINEER}}"


class TemplateError(ValueError):
    """Raised when a Word template cannot be filled as requested."""


_PARAGRAPH_RE = re.compile(rb"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
_TEXT_RE = re.compile(rb"<w:t(?P<attrs>\s[^>]*)?>(?P<text>.*?)</w:t>", re.DOTALL)
_ROW_RE = re.compile(rb"<w:tr(?:\s[^>]*)?>.*?</w:tr>", re.DOTALL)
_CELL_RE = re.compile(rb"<w:tc(?:\s[^>]*)?>.*?</w:tc>", re.DOTALL)


def _text(fragment: bytes) -> str:
    return html.unescape(
        b"".join(match.group("text") for match in _TEXT_RE.finditer(fragment)).decode()
    )


def _replace_text(paragraph: bytes, value: str) -> bytes:
    """Put all visible text in the first run and preserve run properties."""
    matches = list(_TEXT_RE.finditer(paragraph))
    if not matches:
        run_properties = b""
        ppr = re.search(rb"<w:pPr(?:\s[^>]*)?>.*?</w:pPr>", paragraph, re.DOTALL)
        if ppr:
            rpr = re.search(rb"<w:rPr(?:\s[^>]*)?>.*?</w:rPr>", ppr.group(0), re.DOTALL)
            if rpr:
                run_properties = rpr.group(0)
        run = (
            b"<w:r>" + run_properties + b'<w:t xml:space="preserve">'
            + escape(value).encode() + b"</w:t></w:r>"
        )
        return paragraph.replace(b"</w:p>", run + b"</w:p>", 1)
    first = matches[0]
    attrs = first.group("attrs") or b""
    if b"xml:space" not in attrs:
        attrs += b' xml:space="preserve"'
    replacement = b"<w:t" + attrs + b">" + escape(value).encode() + b"</w:t>"
    result = paragraph
    for match in reversed(matches[1:]):
        result = result[:match.start()] + b"<w:t></w:t>" + result[match.end():]
    return result[:first.start()] + replacement + result[first.end():]


def _replace_paragraph(paragraph: bytes, engineer_name: str) -> bytes:
    matches = list(_TEXT_RE.finditer(paragraph))
    joined = b"".join(match.group("text") for match in matches)
    if PLACEHOLDER.encode() not in joined:
        return paragraph
    replaced = html.unescape(joined.decode()).replace(PLACEHOLDER, engineer_name)
    return _replace_text(paragraph, replaced)


def _replace_document(xml: bytes, engineer_name: str) -> bytes:
    return _PARAGRAPH_RE.sub(
        lambda match: _replace_paragraph(match.group(0), engineer_name), xml
    )


def _rewrite_docx(docx_bytes: bytes, rewrite) -> tuple[bytes, bool]:
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes), "r") as source:
            members = [(info, source.read(info.filename)) for info in source.infolist()]
    except (zipfile.BadZipFile, KeyError) as exc:
        raise TemplateError("Invalid Word template") from exc
    names = {info.filename for info, _ in members}
    targets = {
        name for name in names
        if name == "word/document.xml" or re.fullmatch(r"word/(?:header|footer)[^/]*\.xml", name)
    }
    if not targets:
        raise TemplateError("word/document.xml not found in the template")
    output = BytesIO()
    found = False
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        ordered = sorted(members, key=lambda item: item[0].filename != "[Content_Types].xml")
        for info, content in ordered:
            if info.filename in targets:
                replacement = rewrite(content)
                found = found or replacement != content
                content = replacement
            target.writestr(info, content)
    return output.getvalue(), found


def fill_engineer(docx_bytes: bytes, engineer_name: str) -> bytes:
    output, found = _rewrite_docx(
        docx_bytes, lambda content: _replace_document(content, engineer_name)
    )
    if not found:
        raise TemplateError(f"Placeholder {PLACEHOLDER} not found in the template")
    return output


def _fill_inline(paragraph: bytes, hardware: dict[str, str]) -> bytes:
    original = _text(paragraph)
    serial_match = re.search(r"\b(?:SN|Serial)\s*:", original, re.IGNORECASE)
    model_match = re.search(r"\bModel\s*:", original, re.IGNORECASE)
    if not serial_match and not model_match:
        return paragraph
    # The real B.tech template uses one paragraph. Rebuild only its visible text.
    if serial_match and model_match and serial_match.start() < model_match.start():
        serial = hardware.get("serial")
        model = hardware.get("model")
        serial_label = original[serial_match.start():serial_match.end()]
        model_label = original[model_match.start():model_match.end()]
        before = original[:serial_match.start()]
        serial_text = serial if serial else original[serial_match.end():model_match.start()].strip()
        model_text = model if model else original[model_match.end():].strip()
        return _replace_text(
            paragraph, f"{before}{serial_label} {serial_text}      {model_label} {model_text}".rstrip()
        )
    replaced = original
    for match, key in ((serial_match, "serial"), (model_match, "model")):
        if match and hardware.get(key):
            # A one-label paragraph contains only that field's value.
            replaced = original[:match.end()] + " " + hardware[key]
    return _replace_text(paragraph, replaced) if replaced != original else paragraph


def _fill_row(row: bytes, hardware: dict[str, str]) -> bytes:
    cells = list(_CELL_RE.finditer(row))
    if len(cells) < 2:
        return row
    labels = [_text(cell.group(0)).strip().casefold() for cell in cells]
    key = None
    for label, candidate in (
        ("processor", "processor"), ("ram", "ram"), ("hard disk", "disk"),
        ("model", "model"), ("serial", "serial"),
    ):
        if label in labels:
            key = candidate
            break
    if not key or not hardware.get(key):
        return row
    target = cells[1] if key in {"model", "serial"} and len(cells) == 2 else cells[-1]
    paragraphs = list(_PARAGRAPH_RE.finditer(target.group(0)))
    if not paragraphs:
        return row
    paragraph = paragraphs[0]
    replacement = _replace_text(paragraph.group(0), hardware[key])
    cell = target.group(0)
    cell = cell[:paragraph.start()] + replacement + cell[paragraph.end():]
    return row[:target.start()] + cell + row[target.end():]


def fill_form(docx_bytes: bytes, *, engineer: str, hardware: dict) -> bytes:
    """Fill hardware in document.xml and the engineer wherever it occurs."""
    values = {key: str(value).strip() for key, value in hardware.items() if value is not None and str(value).strip()}
    output, found = _rewrite_docx(
        docx_bytes, lambda content: _replace_document(content, engineer)
    )
    if not found:
        raise TemplateError(f"Placeholder {PLACEHOLDER} not found in the template")

    def hardware_xml(content: bytes) -> bytes:
        content = _PARAGRAPH_RE.sub(lambda m: _fill_inline(m.group(0), values), content)
        return _ROW_RE.sub(lambda m: _fill_row(m.group(0), values), content)

    output, _ = _rewrite_docx(output, hardware_xml)
    return output
