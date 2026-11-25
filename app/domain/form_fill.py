"""Fill the engineer placeholder in Word handover templates."""

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


def _replace_paragraph(paragraph: bytes, engineer_name: str) -> bytes:
    """Replace the placeholder in one Word paragraph, preserving other text."""
    matches = list(_TEXT_RE.finditer(paragraph))
    if not matches:
        return paragraph

    joined = b"".join(match.group("text") for match in matches)
    if PLACEHOLDER.encode("utf-8") not in joined:
        return paragraph

    joined_text = html.unescape(joined.decode("utf-8"))
    replaced = joined_text.replace(PLACEHOLDER, engineer_name)
    first = matches[0]
    attrs = first.group("attrs") or b""
    if b"xml:space" not in attrs:
        attrs += b' xml:space="preserve"'
    first_replacement = (
        b"<w:t"
        + attrs
        + b">"
        + escape(replaced, {chr(34): chr(38) + "quot;"}).encode("utf-8")
        + b"</w:t>"
    )

    result = paragraph
    for match in reversed(matches[1:]):
        result = result[: match.start()] + b"<w:t></w:t>" + result[match.end() :]
    result = result[: first.start()] + first_replacement + result[first.end() :]
    return result


def _replace_document(xml: bytes, engineer_name: str) -> bytes:
    def replace(match: re.Match[bytes]) -> bytes:
        return _replace_paragraph(match.group(0), engineer_name)

    return _PARAGRAPH_RE.sub(replace, xml)


def fill_engineer(docx_bytes: bytes, engineer_name: str) -> bytes:
    # Return a valid DOCX with the engineer placeholder replaced by the name.
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes), "r") as source:
            members = [(info, source.read(info.filename)) for info in source.infolist()]
    except (zipfile.BadZipFile, KeyError) as exc:
        raise TemplateError("Invalid Word template") from exc

    names = {info.filename for info, _ in members}
    targets = [
        name
        for name in names
        if name == "word/document.xml"
        or re.fullmatch(r"word/(?:header|footer)[^/]*\.xml", name)
    ]
    if not targets:
        raise TemplateError(f"Placeholder {PLACEHOLDER} not found in the template")

    output = BytesIO()
    found = False
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        ordered = sorted(members, key=lambda item: item[0].filename != "[Content_Types].xml")
        for info, content in ordered:
            if info.filename in targets:
                replacement = _replace_document(content, engineer_name)
                found = found or replacement != content
                content = replacement
            target.writestr(info, content)
    if not found:
        raise TemplateError(f"Placeholder {PLACEHOLDER} not found in the template")
    return output.getvalue()
