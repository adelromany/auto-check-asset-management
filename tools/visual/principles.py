"""Builders for the twelve principle explainers and the visual index."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .artifacts import REPO_ROOT
from .markdown import (
    BLOB_BASE,
    PRINCIPLES_DIR,
    Converter,
    Rule,
    collect_rules,
    link_rule_ids,
    parse_sections,
    slug,
    source_sha256,
)


@dataclass(frozen=True)
class PrinciplePage:
    key: str
    number: str
    title: str
    one_line: str
    diagram: str = ""

    @property
    def markdown_path(self) -> Path:
        return PRINCIPLES_DIR / f"{self.key}.md"


PAGES: tuple[PrinciplePage, ...] = (
    PrinciplePage(
        "01-test-principles",
        "01",
        "Test Principles",
        "The test pyramid, the characterization contract and the checks every change must carry.",
    ),
    PrinciplePage(
        "02-logging-principles",
        "02",
        "Logging Principles",
        "The append-only audit trail and the structured technical log, with the data they must never hold.",
    ),
    PrinciplePage(
        "03-graph-principles",
        "03",
        "Graph Principles",
        "The LIVE GRAPH contract: modules, routes, tables and the rules that keep the map honest.",
    ),
    PrinciplePage(
        "04-security-principles",
        "04",
        "Security Principles",
        "The red line: secrets, identity, input, files and Snipe-IT writes.",
    ),
    PrinciplePage(
        "05-business-principles",
        "05",
        "Business Principles",
        "The handover vocabulary, the ten fixed stages and the rules that decide what is done.",
    ),
    PrinciplePage(
        "06-clean-architecture-and-design-patterns",
        "06",
        "Clean Architecture & Design Patterns",
        "The dependency rule, the patterns that earn their place and the database-session contract.",
        diagram="layers",
    ),
    PrinciplePage(
        "07-ui-ux-principles",
        "07",
        "UI/UX Principles",
        "One consistent server-rendered interface: vocabulary, hierarchy, states and accessibility.",
    ),
    PrinciplePage(
        "08-git-branches-principles",
        "08",
        "Git Branches Principles",
        "Branch names, commit shape and the checks that keep pushed history intact.",
        diagram="branches",
    ),
    PrinciplePage(
        "09-decisions",
        "09",
        "Decisions",
        "Owner decisions and engagement decisions, with status, context and consequences.",
    ),
    PrinciplePage(
        "10-tech-stack-principles",
        "10",
        "Tech Stack Principles",
        "The approved stack, its installed versions and the rules for adding anything new.",
    ),
    PrinciplePage(
        "11-clean-code-principles",
        "11",
        "Clean Code Principles",
        "Names, function and file size, typing, errors and the JavaScript module contract.",
    ),
    PrinciplePage(
        "12-performance-principles",
        "12",
        "Performance Principles",
        "Targets, pagination, SQL aggregates and the performance work that remains unmeasured.",
    ),
)

PAGE_BY_KEY = {page.key: page for page in PAGES}


def _all_rules() -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    for page in PAGES:
        for rule in collect_rules(page.key, page.markdown_path.read_text(encoding="utf-8")):
            rules.setdefault(rule.rule_id, rule)
    return rules


def _opening_paragraph(opening: list[str]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in opening:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        if stripped.startswith(("- ", "|", "#", ">")):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(" ".join(current))
    return " ".join(paragraphs).strip()


def _generated_summary(sections) -> str:
    if not sections:
        return (
            "Summary (generated from the headings): This page records the "
            "rules in the source file."
        )
    noun = "section" if len(sections) == 1 else "sections"
    return (
        f"Summary (generated from the headings): This page has {len(sections)} "
        f"{noun}. It keeps every rule in the source file and adds no new rule."
    )


def _diagram_block(kind: str) -> list[str]:
    if kind == "layers":
        return [
            "## Layers at a glance {#layers-at-a-glance-panel}",
            "",
            "@architecture id=layer-map title=\"Allowed dependency direction\"",
            "| router | routers | frontend |",
            "| service | services | backend |",
            "| data | repositories / clients | backend |",
            "| store | db / external systems | database |",
            "| domain | domain (pure) | backend |",
            "| security | security (HTTP hardening) | security |",
            "| router > service | calls |",
            "| service > data | uses |",
            "| data > store | reads / writes |",
            "| service > domain | pure rules |",
            "| router > security | guarded by |",
            "",
        ]
    if kind == "branches":
        return [
            "## Branch families {#branch-families-panel}",
            "",
            "@tree id=branch-families title=\"Branch name families\"",
            "| root | verified tip | - |",
            "| feature | feature/<name> | root |",
            "| refactor | refactor/<name> | root |",
            "| fix | fix/<bug> | root |",
            "| test | test/<name> | root |",
            "| docs | docs/<name> | root |",
            "| chore | chore/<name> | root |",
            "",
        ]
    return []


def _graph_panel() -> list[str]:
    graph_md = (PRINCIPLES_DIR / "03-graph-principles.md").read_text(encoding="utf-8")
    start = graph_md.find("<!-- GRAPH:START -->")
    end = graph_md.find("<!-- GRAPH:END -->")
    section = graph_md[start:end]
    module_count = len(
        [line for line in section.splitlines() if line.strip().startswith("| module |")]
    )
    import_count = len(
        [line for line in section.splitlines() if re.match(r"^\|\s*\S+\s*\|\s*imports\s*\|", line)]
    )
    route_count = len(
        [line for line in section.splitlines() if line.strip().startswith("| route |")]
    )
    table_count = len(
        [line for line in section.splitlines() if line.strip().startswith("| table |")]
    )
    stage_count = len(
        [line for line in section.splitlines() if line.strip().startswith("| stage |")]
    )
    return [
        "## LIVE GRAPH {#live-graph}",
        "",
        "The node and edge tables in the Markdown file are the machine-checked "
        "source of truth. The diagrams below are generated from that section.",
        "",
        "@facts",
        f"| Module nodes | {module_count} |",
        f"| Import edges | {import_count} |",
        f"| Route nodes | {route_count} |",
        f"| Table nodes | {table_count} |",
        f"| Stage nodes | {stage_count} |",
        "| Architecture overview | `docs/visual/graph/architecture-overview.html` |",
        "| Every module | `docs/visual/graph/architecture-modules.html` |",
        "| Layer focus views | `docs/visual/graph/focus-router.html` and four more |",
        "| Violations | `docs/visual/graph/violations.html` |",
        "| Freshness | `docs/visual/graph/index.html` |",
        "",
        "@callout id=offline-diagrams level=note title=\"Open the diagram files beside this page\"",
        "The graph diagrams are standalone HTML files in `docs/visual/graph/`. "
        "The wrapper page adds the freshness banner and links every view.",
        "",
    ]


def build_explainer(page: PrinciplePage, rules: dict[str, Rule]) -> str:
    text = page.markdown_path.read_text(encoding="utf-8")
    title, opening, sections = parse_sections(text)
    conclusion = _opening_paragraph(opening)
    if not conclusion:
        conclusion = _generated_summary(sections)
    if page.key == "03-graph-principles":
        sections = [section for section in sections if not section.title.startswith("LIVE GRAPH")]
    converter = Converter(
        page_key=page.key,
        title=title or page.title,
        rules=rules,
        path=page.markdown_path,
    )
    body: list[str] = [f"# {converter.title}", "", conclusion, ""]
    diagram = _diagram_block(page.diagram)
    if diagram:
        # Put the structural diagram before the rule panels; the section from
        # the Markdown still appears in full below it.
        body.extend(diagram)
    for index, section in enumerate(sections):
        body.extend(converter._convert_section(section, index))
    if page.key == "03-graph-principles":
        body.extend(_graph_panel())
    body.extend(
        [
            "## Source {#source}",
            "",
            "@facts",
            f"| Source Markdown | `docs/principles/{page.key}.md` |",
            f"| SHA-256 | `{source_sha256(page.markdown_path)}` |",
            f"| Repository link | [Open the Markdown source]({BLOB_BASE}/docs/principles/{page.key}.md) |",
            "",
        ]
    )
    return "\n".join(body).rstrip() + "\n"


def principle_source(page: PrinciplePage) -> str:
    return build_explainer(page, _all_rules())


def rule_count(page: PrinciplePage) -> int:
    return len(collect_rules(page.key, page.markdown_path.read_text(encoding="utf-8")))


INDEX_CSS = """
:root{color-scheme:light dark;--bg:#f6f7f9;--panel:#ffffff;--ink:#16181d;--muted:#5c6370;
--line:#d9dde5;--accent:#0b63ce;--accent-soft:#e8f1fd;--shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#101216;--panel:#171a20;--ink:#e8ebf1;--muted:#9aa3b2;
--line:#2a2f3a;--accent:#6aa8ff;--accent-soft:#152238;--shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:48px 24px 80px}
header.top{display:flex;gap:24px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.eyebrow{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:700}
h1{font-size:34px;line-height:1.15;margin:8px 0 10px;letter-spacing:-.02em}
.lede{color:var(--muted);max-width:62ch;margin:0}
.search{margin:28px 0 8px;position:relative;max-width:420px}
.search input{width:100%;padding:11px 14px;border:1px solid var(--line);border-radius:10px;
background:var(--panel);color:var(--ink);font:inherit;outline:none}
.search input:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;margin-top:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 18px 16px;
box-shadow:var(--shadow);display:flex;flex-direction:column;gap:8px;min-height:150px}
.card .num{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:var(--muted);letter-spacing:.08em}
.card h2{font-size:17px;line-height:1.3;margin:0}
.card p{margin:0;color:var(--muted);font-size:14px}
.meta{margin-top:auto;padding-top:10px;border-top:1px solid var(--line);display:flex;justify-content:space-between;
gap:8px;font-size:12px;color:var(--muted)}
.pill{background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:2px 9px;font-weight:600}
.feature{border-color:var(--accent)}
footer{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
.hidden{display:none}
"""

INDEX_JS = """
const input=document.querySelector('[data-search]');
const cards=[...document.querySelectorAll('[data-card]')];
const empty=document.querySelector('[data-empty]');
if(input){input.addEventListener('input',()=>{const q=input.value.trim().toLowerCase();let shown=0;
for(const card of cards){const hit=!q||card.textContent.toLowerCase().includes(q);
card.classList.toggle('hidden',!hit);if(hit)shown++;}
if(empty)empty.classList.toggle('hidden',shown!==0);});}
"""


def build_index() -> str:
    cards: list[str] = []
    for page in PAGES:
        count = rule_count(page)
        cards.append(
            f"""      <a class="card" data-card href="{html.escape(page.key)}.html">
        <span class="num">PRINCIPLE {page.number}</span>
        <h2>{html.escape(page.title)}</h2>
        <p>{html.escape(page.one_line)}</p>
        <span class="meta"><span>{count} rules</span><span class="pill">Read</span></span>
      </a>"""
        )
    graph_card = f"""      <a class="card" data-card href="graph/index.html">
        <span class="num">INTERACTIVE DIAGRAMS</span>
        <h2>LIVE GRAPH</h2>
        <p>Architecture, layer focus views, violations and freshness, generated from the machine-checked graph.</p>
        <span class="meta"><span>Archify architecture</span><span class="pill">Explore</span></span>
      </a>"""
    handover_card = f"""      <a class="card feature" data-card href="handover/index.html">
        <span class="num">DEVICE HANDOVER WORKFLOW</span>
        <h2>Device handover workflow</h2>
        <p>Every stage, the onboarding sequence, the status lifecycle, the database model and the code-versus-briefing differences.</p>
        <span class="meta"><span>Workflow · sequence · lifecycle · ERD</span><span class="pill">Open</span></span>
      </a>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visual documentation</title>
<style>{INDEX_CSS}</style>
</head>
<body>
<main class="wrap">
  <header class="top">
    <div>
      <div class="eyebrow">auto-check-asset-management</div>
      <h1>Visual documentation</h1>
      <p class="lede">The twelve principle files and the code-derived handover workflow, rendered as offline Archify pages. The Markdown and the application code remain the source of truth.</p>
    </div>
  </header>
  <div class="search"><input type="search" data-search placeholder="Search pages and rules…" aria-label="Search pages and rules"></div>
  <section class="grid" aria-live="polite">
{chr(10).join(cards)}
{graph_card}
{handover_card}
  </section>
  <p data-empty class="hidden">No page matches that search.</p>
  <footer>Generated with Archify 3.2.0 from the committed Markdown and code. Open any card; the pages work offline.</footer>
</main>
<script>{INDEX_JS}</script>
</body>
</html>
"""
