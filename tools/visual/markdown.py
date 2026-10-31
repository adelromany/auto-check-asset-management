"""Deterministic Markdown-to-Archify-explainer conversion.

The principle files stay the source of truth.  This module only rearranges
their content into the explainer draft language: it never changes rule text,
tables, code blocks or checklists.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRINCIPLES_DIR = REPO_ROOT / "docs" / "principles"
REPO_URL = "https://github.com/adelromany/auto-check-asset-management"
BLOB_BASE = f"{REPO_URL}/blob/main"

RULE_RE = re.compile(r"^-\s+([A-Z]{3}-\d{2})\b\s*(.*)$")
DECISION_RE = re.compile(r"^-\s+([DQ]-\d{2})\b\s*(.*)$")
ID_RE = re.compile(r"\b([A-Z]{3}-\d{2})\b")
CODE_SPAN_RE = re.compile(r"`[^`]*`")
LINK_RE = re.compile(r"\[[^\]]*\]\([^)]*\)")


@dataclass
class Rule:
    rule_id: str
    page_key: str
    line: int
    text: str

    @property
    def anchor(self) -> str:
        return self.rule_id.lower()

    @property
    def github_url(self) -> str:
        return f"{BLOB_BASE}/docs/principles/{self.page_key}.md#L{self.line}"


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)


def slug(text: str, fallback: str = "section") -> str:
    value = text.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if not value or not value[0].isalpha():
        value = fallback + ("-" + value if value else "")
    return value[:60]


def source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_sections(text: str) -> tuple[str, list[str], list[Section]]:
    """Return ``(title, opening_lines, sections)``."""
    lines = text.splitlines()
    title = ""
    start = 0
    for index, line in enumerate(lines):
        if line.startswith("# "):
            title = line[2:].strip()
            start = index + 1
            break
    opening: list[str] = []
    sections: list[Section] = []
    current: Section | None = None
    parent = ""
    in_fence = False
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            if current is not None:
                sections.append(current)
            parent = line[3:].strip()
            current = Section(parent)
            continue
        if not in_fence and line.startswith("### "):
            if current is not None:
                sections.append(current)
            current = Section(f"{parent} — {line[4:].strip()}")
            continue
        if current is None:
            opening.append(line)
        else:
            current.lines.append(line)
    if current is not None:
        sections.append(current)
    return title, opening, sections


def collect_rules(page_key: str, text: str) -> list[Rule]:
    rules: list[Rule] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = RULE_RE.match(line.strip())
        if match:
            rules.append(Rule(match.group(1), page_key, number, match.group(2).strip()))
    return rules


def _join_paragraph(lines: list[str]) -> str:
    parts = [line.strip() for line in lines if line.strip()]
    return " ".join(parts)


def _plain_segments(text: str):
    """Yield ``(segment, protected)`` pieces so IDs in code/links stay literal."""
    protected: list[tuple[int, int]] = []
    for pattern in (CODE_SPAN_RE, LINK_RE):
        protected.extend((m.start(), m.end()) for m in pattern.finditer(text))
    protected.sort()
    cursor = 0
    for start, end in protected:
        if start < cursor:
            continue
        if cursor < start:
            yield text[cursor:start], False
        yield text[start:end], True
        cursor = end
    if cursor < len(text):
        yield text[cursor:], False


def link_rule_ids(
    text: str,
    *,
    page_key: str,
    rules: dict[str, Rule],
) -> str:
    """Link known rule IDs; same-page targets use Archify block links."""
    pieces: list[str] = []
    for segment, protected in _plain_segments(text):
        if protected:
            pieces.append(segment)
            continue

        def replace(match: re.Match[str]) -> str:
            rule_id = match.group(1)
            target = rules.get(rule_id)
            if target is None:
                return rule_id
            if target.page_key == page_key:
                return f"[{rule_id}](block:{target.anchor})"
            return f"[{rule_id}]({target.github_url})"

        pieces.append(ID_RE.sub(replace, segment))
    return "".join(pieces)


def _escape_cell(text: str) -> str:
    return text.replace("|", "\\|")


def _is_table_start(lines: list[str], index: int) -> bool:
    return (
        lines[index].lstrip().startswith("|")
        and index + 1 < len(lines)
        and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[index + 1]) is not None
    )


@dataclass
class Converter:
    page_key: str
    title: str
    rules: dict[str, Rule]
    path: Path

    def _convert_list(self, items: list[str], panel: Section) -> list[str]:
        """Convert a top-level list into a table when it carries rule IDs.

        Table cells are the one explainer surface where Archify does not apply
        prose sentence-length rules, so the exact source sentence can stay
        untouched.  The row label carries the rule ID as a stable anchor.
        """
        matches = [RULE_RE.match(item) or DECISION_RE.match(item) for item in items]
        if not any(matches):
            return self._plain_list(items)
        rows: list[str] = [
            "| Rule | Text |",
            "| --- | --- |",
        ]
        leftovers: list[str] = []
        for item, match in zip(items, matches):
            if not match:
                leftovers.append(item)
                continue
            rule_id = match.group(1)
            text = match.group(2).strip()
            text = link_rule_ids(text, page_key=self.page_key, rules=self.rules)
            rows.append(
                f"| {_escape_cell(rule_id)} {{#{rule_id.lower()}}} | "
                f"{_escape_cell(text)} |"
            )
        out = [*rows, ""]
        out.extend(self._plain_list(leftovers))
        return out

    def _plain_list(self, items: list[str]) -> list[str]:
        if not items:
            return []
        checklist = all(item.strip().startswith("- [ ]") for item in items)
        out: list[str] = []
        for item in items:
            text = item.strip()
            text = link_rule_ids(text, page_key=self.page_key, rules=self.rules)
            out.append(text)
        return out + [""]

    def _convert_section(self, section: Section, index: int) -> list[str]:
        panel_id = f"{slug(section.title, f'panel-{index}')}-{index}"
        lines = section.lines
        out: list[str] = [f"## {section.title} {{#{panel_id}}}", ""]
        pending: list[str] = []
        list_items: list[str] = []
        table: list[str] = []
        code: list[str] = []
        in_fence = False
        fence: list[str] = []
        i = 0

        def flush_paragraph() -> None:
            nonlocal pending
            if pending:
                text = link_rule_ids(
                    _join_paragraph(pending), page_key=self.page_key, rules=self.rules
                )
                out.extend([text, ""])
                pending = []

        def flush_list() -> None:
            nonlocal list_items
            if list_items:
                out.extend(self._convert_list(list_items, section))
                list_items = []

        def flush_table() -> None:
            nonlocal table
            if table:
                out.extend(self._table_with_row_ids(table))
                out.append("")
                table = []

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if in_fence:
                fence.append(line)
                if stripped.startswith("```"):
                    in_fence = False
                    out.extend(fence)
                    out.append("")
                    fence = []
                i += 1
                continue

            if stripped.startswith("```"):
                flush_paragraph()
                flush_list()
                flush_table()
                in_fence = True
                fence = [line]
                i += 1
                continue

            if not stripped:
                flush_paragraph()
                flush_list()
                flush_table()
                i += 1
                continue

            if line.lstrip().startswith("|"):
                flush_paragraph()
                flush_list()
                table.append(line.rstrip())
                i += 1
                continue
            if table:
                flush_table()

            if stripped.startswith("- "):
                flush_paragraph()
                list_items.append(stripped)
                # Keep wrapped continuation lines inside the same item.
                j = i + 1
                continuation = []
                while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
                    continuation.append(lines[j].strip())
                    j += 1
                if continuation:
                    list_items[-1] = list_items[-1] + " " + " ".join(continuation)
                i = j
                continue
            if list_items:
                flush_list()

            if re.match(r"^\d+\.\s+", stripped):
                flush_paragraph()
                out.append(stripped)
                i += 1
                continue

            pending.append(stripped)
            i += 1

        flush_paragraph()
        flush_list()
        flush_table()
        if in_fence and fence:
            out.extend(fence)
            out.append("")

        return out

    def _table_with_row_ids(self, lines: list[str]) -> list[str]:
        """Give every data row a unique anchor without changing cell text."""
        result: list[str] = []
        seen: dict[str, int] = {}
        data_started = False
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|"):
                result.append(line)
                continue
            cells = stripped.strip("|").split("|")
            if not data_started:
                result.append(line)
                if len(cells) >= 2 and re.match(r"^[\s:|-]+$", cells[1].strip()):
                    data_started = True
                continue
            first = cells[0].strip()
            if "{#" in first:
                result.append(line)
                continue
            base = slug(re.sub(r"[`*_]", "", first), "row") or "row"
            count = seen.get(base, 0) + 1
            seen[base] = count
            anchor = base if count == 1 else f"{base}-{count}"
            cells[0] = f" {first} {{#{anchor}}} "
            result.append("|" + "|".join(cells) + "|")
        return result

    def convert(self, sections: list[Section], *, conclusion: str, reasons: list[str]) -> str:
        lines: list[str] = [f"# {self.title}", "", conclusion, ""]
        for reason in reasons:
            lines.append(f"- {reason}")
        if reasons:
            lines.append("")
        for index, section in enumerate(sections):
            lines.extend(self._convert_section(section, index))
        lines.extend(
            [
                "## Source {#source}",
                "",
                "@facts",
                f"| Source Markdown | `docs/principles/{self.page_key}.md` |",
                f"| SHA-256 | `{source_sha256(self.path)}` |",
                f"| Repository link | [Open the Markdown source]({BLOB_BASE}/docs/principles/{self.page_key}.md) |",
                "",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"
