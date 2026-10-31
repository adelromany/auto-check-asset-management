"""Deterministic offline generator for the principle visual pages."""

from __future__ import annotations

import argparse
import ast
import hashlib
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.domain.stages import HandoverStatus, STAGE_DEPENDENCIES, STAGE_ORDER, Stage, StageStatus
from tools.build_handover_workflow import OUT as WORKFLOW_OUT, workflow_html as handover_workflow_html
from tools.graph_data import GraphData, actual_modules, parse_graph

DOCS = ROOT / "docs" / "principles"
OUT = DOCS / "visual"
CSS = OUT / "assets" / "visual.css"
JS = OUT / "assets" / "visual.js"
PALETTE = {
    "router": "#0969DA", "service": "#1A7F37", "repository": "#9A6700",
    "client": "#9A6700", "db": "#8250DF", "external": "#8250DF",
    "domain": "#0A7C86", "dto": "#0969DA", "config": "#57606A", "infra": "#57606A",
}
TINTS = {"router": "#EAF2FC", "service": "#EAF5ED", "repository": "#F7F0E1", "client": "#F7F0E1", "db": "#F0EAFB", "external": "#F0EAFB", "domain": "#E8F4F4", "dto": "#F1F3F5", "config": "#F1F3F5", "infra": "#F1F3F5"}


@dataclass(frozen=True)
class RenderedMarkdown:
    html: str
    broken_references: set[str]


def slug(text: str) -> str:
    value = re.sub(r"<[^>]+>", "", text).strip().casefold()
    value = re.sub(r"[^\w -]", "", value, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", value).strip("-")


def _inline(text: str, known_rule_ids: set[str] | None, broken: set[str]) -> str:
    value = html.escape(text, quote=False)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', value)
    def rule(match: re.Match[str]) -> str:
        rid = match.group(0)
        if known_rule_ids is not None and rid not in known_rule_ids:
            broken.add(rid)
            return f'<span class="broken-ref">{rid}</span>'
        return f'<a class="rule-badge" id="{rid}" href="#{rid}">{rid}</a>'
    value = re.sub(r"\b(?:ARC|BIZ|CLN|DEP|GIT|LOG|PRF|SEC|TST|UX)-\d{2,3}\b", rule, value)
    return value


def markdown_to_html(source: str, known_rule_ids: set[str] | None = None) -> RenderedMarkdown:
    """Render the repository's Markdown subset using only the standard library."""
    lines = source.splitlines()
    output: list[str] = []
    broken: set[str] = set()
    i = 0
    list_stack: list[tuple[int, str]] = []
    def close_lists() -> None:
        while list_stack:
            _, tag = list_stack.pop()
            output.append(f"</{tag}>")
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            close_lists(); i += 1; continue
        if line.startswith("```"):
            close_lists(); language = line[3:].strip(); code: list[str] = []; i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i]); i += 1
            output.append(f'<div class="code-wrap"><pre dir="auto"><code class="language-{html.escape(language)}">{html.escape(chr(10).join(code))}</code></pre></div>')
            i += 1; continue
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            close_lists(); headers = [x.strip() for x in line.strip().strip("|").split("|")]; i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                rows.append(cells); i += 1
            output.append('<div class="table-wrap" tabindex="0" role="region" aria-label="Scrollable table"><table><thead><tr>')
            output.extend(f'<th scope="col" dir="auto">{_inline(x, known_rule_ids, broken)}</th>' for x in headers)
            output.append("</tr></thead><tbody>")
            for row in rows:
                output.append("<tr>" + "".join(f'<td dir="auto">{_inline(x, known_rule_ids, broken)}</td>' for x in row) + "</tr>")
            output.append("</tbody></table></div>"); continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading:
            close_lists(); level = len(heading.group(1)); title = heading.group(2)
            hid = slug(re.sub(r"`([^`]+)`", r"\1", title))
            output.append(f'<h{level} id="{hid}" dir="auto">{_inline(title, known_rule_ids, broken)}</h{level}>')
            i += 1; continue
        bullet = re.match(r"^(\s*)([-+*]|\d+\.)\s+(.*)$", line)
        if bullet:
            indent = len(bullet.group(1).expandtabs(2)); tag = "ol" if bullet.group(2)[0].isdigit() else "ul"
            while list_stack and (list_stack[-1][0] > indent or (list_stack[-1][0] == indent and list_stack[-1][1] != tag)):
                _, old = list_stack.pop(); output.append(f"</li></{old}>")
            if not list_stack or list_stack[-1][0] < indent:
                if list_stack: output.append("<li>")
                output.append(f"<{tag}>"); list_stack.append((indent, tag))
            else:
                output.append("</li><li>")
            content = bullet.group(3)
            if content.startswith("[ ] ") or content.startswith("[x] "):
                checked = " checked" if content.startswith("[x]") else ""
                content = re.sub(r"^\[[ xX]\]\s*", "", content)
                content = f'<input type="checkbox" disabled{checked}> {content}'
            output.append(f'<li dir="auto">{_inline(content, known_rule_ids, broken)}')
            i += 1; continue
        if list_stack: close_lists()
        if line.startswith("> "):
            output.append(f'<blockquote dir="auto">{_inline(line[2:], known_rule_ids, broken)}</blockquote>')
        else:
            output.append(f'<p dir="auto">{_inline(line, known_rule_ids, broken)}</p>')
        i += 1
    close_lists()
    return RenderedMarkdown("\n".join(output), broken)


def extract_graph(source: str) -> GraphData:
    return parse_graph(source)


def parse_stages(source: str) -> tuple[list[str], list[tuple[str, str]]]:
    names = re.findall(r"^\s+[A-Z][A-Z0-9_]+\s*=\s*['\"]([^'\"]+)['\"]", source, re.M)
    order_block = re.search(r"STAGE_ORDER\s*:[^=]*=\s*\((.*?)\)", source, re.S)
    if order_block:
        keys = re.findall(r"Stage\.([A-Z][A-Z0-9_]*)", order_block.group(1))
        enum_to_value = dict(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", source, re.M))
        names = [enum_to_value[k] for k in keys]
    deps: list[tuple[str, str]] = []
    dep_block = re.search(r"STAGE_DEPENDENCIES\s*(?::[^=]*)?=\s*\{(.*?)\}", source, re.S)
    if dep_block:
        for key, values in re.findall(r"Stage\.([A-Z][A-Z0-9_]*):\s*\(([^)]*)\)", dep_block.group(1)):
            target = dict(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", source, re.M)).get(key)
            for dependency in re.findall(r"Stage\.([A-Z][A-Z0-9_]*)", values):
                dep_value = dict(re.findall(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*['\"]([^'\"]+)['\"]", source, re.M)).get(dependency)
                if target and dep_value: deps.append((target, dep_value))
    return names, deps


def contrast_ratio(foreground: str, background: str) -> float:
    def lum(color: str) -> float:
        channels = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
        return sum(w * c for w, c in zip((.2126, .7152, .0722), linear))
    high, low = sorted((lum(foreground), lum(background)), reverse=True)
    return (high + .05) / (low + .05)


def checked_contrasts() -> list[tuple[str, str, str, float]]:
    pairs = [("body", "#1F2328", "#FFFFFF", 7.0), ("muted", "#57606A", "#FFFFFF", 4.5), ("surface", "#1F2328", "#F6F8FA", 7.0), ("dark body", "#E6EDF3", "#0F1419", 7.0), ("dark muted", "#9AA4AF", "#0F1419", 4.5), ("dark surface", "#E6EDF3", "#161B22", 7.0)]
    for layer, color in (("routers", "#0969DA"), ("services", "#1A7F37"), ("repositories/clients", "#9A6700"), ("db/external", "#8250DF"), ("domain", "#0A7C86")):
        for theme, backgrounds in (("light", ("#FFFFFF", "#F6F8FA")), ("dark", ("#0F1419", "#161B22"))):
            for bg in backgrounds: pairs.append((f"{layer} {theme}", color, bg, 3.0))
    for label, color in (("ok icon", "#1A7F37"), ("warning icon", "#9A6700"), ("error icon", "#CF222E")):
        for theme, backgrounds in (("light", ("#FFFFFF", "#F6F8FA")), ("dark", ("#0F1419", "#161B22"))):
            for bg in backgrounds: pairs.append((f"{label} {theme}", color, bg, 3.0))
    result = []
    for label, fg, bg, minimum in pairs:
        ratio = contrast_ratio(fg, bg)
        if ratio < minimum: raise ValueError(f"Contrast failure {label}: {ratio:.2f}:1 < {minimum}:1")
        result.append((label, fg, bg, ratio))
    return result


def _module_layer(path: str) -> str:
    parts = path.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "app" else "infra"


def _imports_by_module(graph: GraphData) -> dict[str, list[str]]:
    known = {path for path, _, _ in graph.modules}
    result = {path: [] for path, _, _ in graph.modules}
    for source, target in graph.imports:
        if source in known and target in known: result[source].append(target)
    return result


def _module_diagrams(graph: GraphData, imports: dict[str, list[str]]) -> str:
    layers = list(dict.fromkeys(layer for _, layer, _ in graph.modules))
    parts = ['<div class="layer-tabs" role="tablist" aria-label="Select architecture layer">']
    for index, layer in enumerate(layers):
        parts.append(f'<button type="button" role="tab" aria-selected="{"true" if index == 0 else "false"}" data-layer-tab="{html.escape(layer)}">{html.escape(layer)}</button>')
    parts.append('</div><div class="layer-details">')
    for index, layer in enumerate(layers):
        modules = [(path, responsibility) for path, declared, responsibility in graph.modules if declared == layer]
        width, node_w, node_h, gap_x, gap_y, cols = 1400, 260, 56, 32, 28, 4
        rows = (len(modules) + cols - 1) // cols
        height = max(130, rows * (node_h + gap_y) + 50)
        layer_color = PALETTE.get(layer, "#57606A")
        nodes = []
        for pos, (path, _) in enumerate(modules):
            x = 24 + (pos % cols) * (node_w + gap_x); y = 25 + (pos // cols) * (node_h + gap_y)
            short = Path(path).stem
            line_count = len((ROOT / path).read_text(encoding="utf-8").splitlines()) if (ROOT / path).is_file() else 0
            outgoing = imports.get(path, [])
            incoming = [src for src, targets in imports.items() if path in targets]
            nodes.append(f'<g class="graph-node" tabindex="0" role="button" aria-label="Open details for {html.escape(short)}" data-module="{html.escape(path)}" data-layer="{html.escape(layer)}" data-lines="{line_count}" data-imports="{html.escape("|".join(outgoing))}" data-importers="{html.escape("|".join(incoming))}"><title>{html.escape(path)} — {html.escape(_dict_get(graph.modules, path))}</title><rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="6" style="--node-color:{layer_color};--node-tint:{TINTS.get(layer, "#F1F3F5")}"/><text x="{x+12}" y="{y+35}" font-size="15">{html.escape(short)}</text></g>')
        parts.append(f'<div class="layer-detail" role="tabpanel" data-layer-panel="{html.escape(layer)}"{" hidden" if index else ""}><h3>{html.escape(layer)} · {len(modules)} modules</h3><div class="diagram-scroll"><svg xmlns="http://www.w3.org/2000/svg" class="graph-svg module-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(layer)} modules">{"".join(nodes)}</svg></div><ul class="module-list">')
        for path, responsibility in modules:
            targets = imports.get(path, [])
            imports_text = ", ".join(Path(target).stem for target in targets) or "No listed imports"
            parts.append(f'<li data-module-row="{html.escape(path)}"><code>{html.escape(Path(path).stem)}</code> · <span title="{html.escape(path)}">{html.escape(path)}</span> — {html.escape(responsibility)}<br><small>Imports: {html.escape(imports_text)}</small></li>')
        parts.append('</ul></div>')
    parts.append('</div>')
    return ''.join(parts)


def _dict_get(modules: list[tuple[str, str, str]], path: str) -> str:
    return next((responsibility for module, _, responsibility in modules if module == path), "")


def _graph_panel(graph: GraphData, source: str) -> str:
    layers: dict[str, list[tuple[str, str, str]]] = {}
    for item in graph.modules: layers.setdefault(item[1], []).append(item)
    colors = {"router": "#0969DA", "service": "#1A7F37", "repository": "#9A6700", "client": "#9A6700", "db": "#8250DF", "domain": "#0A7C86"}
    overview = []
    for row, (layer, items) in enumerate(layers.items()):
        y = 24 + row * 162; color = colors.get(layer, "#57606A")
        marker = ["◆", "●", "▲", "■", "⬟", "○", "◇", "✦", "□"][row % 9]
        overview.append(f'<g class="layer-band" data-layer="{html.escape(layer)}"><rect x="24" y="{y}" width="1352" height="72" rx="8" style="--layer-color:{color}"/><text x="48" y="{y+31}" class="marker" font-size="21">{marker}</text><text x="88" y="{y+32}" class="band-name" font-size="20">{html.escape(layer)}</text><text x="88" y="{y+56}" class="band-count" font-size="15">{len(items)} modules</text></g>')
    band_height = 44 + max(1, len(layers)) * 162
    overview_svg = f'<div class="diagram-scroll"><svg xmlns="http://www.w3.org/2000/svg" class="graph-svg overview-svg" width="1400" height="{band_height}" viewBox="0 0 1400 {band_height}" role="img" aria-label="Application layers overview">{"".join(overview)}</svg></div>'
    layer_details = _module_diagrams(graph, _imports_by_module(graph))
    stage_svg = _stage_flow_svg()
    violations = _architecture_violations(graph)
    app_files = sorted((ROOT / "app").rglob("*.py"))
    current_source = source + "\n" + "\n".join(f.relative_to(ROOT).as_posix() + ":" + hashlib.sha256(f.read_bytes()).hexdigest() for f in app_files)
    freshness = hashlib.sha256(current_source.encode("utf-8")).hexdigest()[:12]
    violation_html = f'<p class="status-ok"><span aria-hidden="true">✓</span> 0 violations · <b>Architecture checks clean</b></p>' if not violations else f'<p class="status-error"><span aria-hidden="true">✕</span> {len(violations)} violations</p><ul class="status-error">' + ''.join(f'<li>✕ {html.escape(item)}</li>' for item in violations) + '</ul>'
    return f'''<section class="graph-section" id="layers-overview"><h2>1. Layers overview</h2><p>Read from outer entry points toward storage and external systems. The downward arrow marks the permitted dependency direction; domain logic stays independent.</p><div class="legend-sticky"><span>◆ Routers</span><span>● Services</span><span>▲ Repositories / clients</span><span>■ Database / external</span><span>⬟ Domain</span></div>{overview_svg}<p class="direction-label">Allowed dependency direction ↓</p></section>
<section class="graph-section" id="layer-detail"><h2>2. Per-layer detail</h2><p>Choose one layer. Each box names a Python module; its complete path and responsibility appear below.</p>{layer_details}</section>
<section class="graph-section" id="dependency-focus"><h2>3. Dependency focus</h2><p>Select a module box or search result. Only its direct imports and importers stay bright; all other modules dim. Use the side panel for paths and line counts.</p><label class="graph-search">Find module <input type="search" data-module-search placeholder="software_check"></label><div class="graph-focus-layout"><div class="graph-focus-note" data-focus-empty>Select a module in the per-layer detail section.</div><aside class="module-details" data-module-details hidden><h3 data-detail-name>Module details</h3><dl><dt>Layer</dt><dd data-detail-layer></dd><dt>File path</dt><dd><code data-detail-path></code></dd><dt>Lines</dt><dd data-detail-lines></dd><dt>Imports</dt><dd data-detail-imports></dd><dt>Imported by</dt><dd data-detail-importers></dd></dl></aside></div></section>
<section class="graph-section" id="handover-stage-flow"><h2>4. Handover stage flow</h2><p>Numbered stages are in executable code order. Arrows show prerequisites. Use the zoom controls or scroll horizontally.</p><div class="diagram-scroll stage-scroll">{stage_svg}</div><p class="stage-statuses">Stage statuses: {', '.join(s.value for s in StageStatus)} · Case statuses: {', '.join(s.value for s in HandoverStatus)}</p></section>
<section class="graph-section" id="violations-freshness"><h2>5. Violations and freshness</h2>{violation_html}<p class="freshness"><span aria-hidden="true">✓</span> Current · source SHA-256 {freshness}</p><p>Build time is intentionally omitted so output stays deterministic.</p></section>'''


def _architecture_violations(graph: GraphData) -> list[str]:
    violations: list[str] = []
    for relative in sorted((ROOT / "app" / "domain").rglob("*.py")):
        if relative.name == "__init__.py": continue
        for node in ast.walk(ast.parse(relative.read_text(encoding="utf-8"), filename=str(relative))):
            module = node.module if isinstance(node, ast.ImportFrom) and node.level == 0 else None
            imported = ([alias.name for alias in node.names] if isinstance(node, ast.Import) else ([module] if module else []))
            for name in imported:
                root = name.split(".")[0]
                if root not in sys.stdlib_module_names:
                    violations.append(f"ARC-01 {relative.relative_to(ROOT).as_posix()} imports non-stdlib module {name}")
    for package, forbidden, rule in (("routers", ("app.db", "httpx"), "ARC-05"), ("services", ("fastapi",), "ARC-04")):
        for relative in sorted((ROOT / "app" / package).rglob("*.py")):
            if relative.name == "__init__.py": continue
            for node in ast.walk(ast.parse(relative.read_text(encoding="utf-8"), filename=str(relative))):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else ([node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module else [])
                for imported in modules:
                    if any(imported == prefix or imported.startswith(prefix + ".") for prefix in forbidden):
                        violations.append(f"{rule} {relative.relative_to(ROOT).as_posix()} imports forbidden module {imported}")
    listed = {path for path, _, _ in graph.modules}
    actual = actual_modules(ROOT / "app", ROOT)
    for path in sorted(actual - listed): violations.append(f"GRF-04 {path} missing from LIVE GRAPH")
    for path in sorted(listed - actual):
        if path.startswith("app/") and path.endswith(".py") and not (ROOT / path).is_file():
            violations.append(f"GRF-04 LIVE GRAPH lists missing module {path}")
    return violations


def _stage_flow_svg() -> str:
    node_w, node_h, gap, pad, node_y, height = 190, 86, 58, 24, 220, 340
    width = pad * 2 + len(STAGE_ORDER) * node_w + (len(STAGE_ORDER) - 1) * gap
    markers = '<defs><marker id="stage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z"/></marker></defs>'
    edges = []
    positions = {stage: (pad + i * (node_w + gap), node_y) for i, stage in enumerate(STAGE_ORDER)}
    edge_index = 0
    for stage in STAGE_ORDER:
        for dep in STAGE_DEPENDENCIES[stage]:
            sx, _ = positions[dep]; tx, _ = positions[stage]
            start_x = sx + node_w / 2; end_x = tx + node_w / 2
            track_y = 178 - edge_index * 10
            edges.append(f'<path class="edge" stroke-width="1.7" d="M {start_x} {node_y} V {track_y} H {end_x} V {node_y}" marker-end="url(#stage-arrow)" data-source="{stage.value}" data-target="{dep.value}"><title>1 dependency edge: {dep.value} → {stage.value}</title></path>')
            edge_index += 1
    nodes = []
    for i, stage in enumerate(STAGE_ORDER, 1):
        x, y = positions[stage]; label = stage.value.replace("_", " ")
        count = len(STAGE_DEPENDENCIES[stage])
        prerequisite_label = f"Requires {count} prior step{'s' if count != 1 else ''}" if count else "Starting step"
        nodes.append(f'<g class="stage-node" tabindex="0" role="button" data-stage="{stage.value}" aria-label="Focus stage {label}"><rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="8"/><text class="stage-number" x="{x+12}" y="{y+26}" font-size="15">{i:02}</text><text class="stage-label" x="{x+45}" y="{y+28}" font-size="15">{html.escape(label)}</text><text class="stage-sub" x="{x+12}" y="{y+62}" font-size="14">{prerequisite_label}</text></g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" class="graph-svg stage-svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Handover stages and prerequisite arrows">{markers}{"".join(edges)}{"".join(nodes)}</svg>'


def _rule_ids() -> set[str]:
    ids = set()
    for path in DOCS.glob("*.md"):
        ids.update(re.findall(r"\b(?:ARC|BIZ|CLN|DEP|GIT|LOG|PRF|SEC|TST|UX)-\d{2,3}\b", path.read_text(encoding="utf-8")))
    return ids


def _page(source_path: Path, known: set[str]) -> str:
    source = source_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    graph_marker = "GRAPH_VISUAL_PLACEHOLDER"
    if source_path.name == "03-graph-principles.md":
        graph = extract_graph(source)
        source = re.sub(r"<!-- GRAPH:START -->.*?<!-- GRAPH:END -->", graph_marker, source, flags=re.S)
        rendered = markdown_to_html(source, known)
        rendered_html = rendered.html.replace(f'<p dir="auto">{graph_marker}</p>', _graph_panel(graph, source_path.read_text(encoding="utf-8")))
        toc_items = re.findall(r'<h([2-4]) id="([^"]+)"[^>]*>(.*?)</h\1>', rendered_html)
        toc = ''.join(f'<a class="toc-level-{level}" href="#{anchor}">{label}</a>' for level, anchor, label in toc_items)
        page_title = re.search(r"^#\s+(.+)$", source, re.M).group(1)
        return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>{html.escape(page_title)}</title><link rel="stylesheet" href="assets/visual.css"><script defer src="assets/visual.js"></script></head><body data-page="graph"><header class="site-header"><a href="index.html">Principles</a><strong>H-Caliper Principles</strong><label class="search-label">Search graph <input data-search type="search" aria-label="Search graph"></label><button type="button" data-theme>Theme</button><button type="button" data-toggle-rail aria-expanded="true">Hide contents</button></header><div class="full-layout"><nav class="toc-rail" aria-label="Contents"><strong>On this page</strong>{toc}</nav><main class="principle-main"><p class="generated">Generated from <code>{source_path.name}</code> · SHA-256 {digest}</p>{rendered_html}</main></div></body></html>'
    rendered = markdown_to_html(source, known)
    title = re.search(r"^#\s+(.+)$", source, re.M)
    page_title = title.group(1) if title else source_path.stem
    toc_items = re.findall(r'<h([2-6]) id="([^"]+)"[^>]*>(.*?)</h\1>', rendered.html)
    toc = ''.join(f'<a class="toc-level-{level}" href="#{anchor}">{label}</a>' for level, anchor, label in toc_items)
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>{html.escape(page_title)}</title><link rel="stylesheet" href="assets/visual.css"><script defer src="assets/visual.js"></script></head><body data-page="principle"><header class="site-header"><a href="index.html">Principles</a><strong>H-Caliper Principles</strong><label class="search-label">Search this principle <input data-search type="search" aria-label="Search principle"></label><button type="button" data-theme>Theme</button><button type="button" data-toggle-rail aria-expanded="true">Hide contents</button></header><div class="layout"><nav class="toc-rail" aria-label="Contents"><strong>On this page</strong>{toc}</nav><main class="principle-main"><p class="generated">Generated from <code>{source_path.name}</code> · SHA-256 {digest}</p>{rendered.html}</main></div></body></html>'


def _index(sources: list[Path]) -> str:
    cards = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        title_match = re.search(r"^#\s+(.+)$", text, re.M); title = title_match.group(1) if title_match else path.stem
        rules = len(re.findall(r"^\s*[-*]\s+[^\n]*\b(?:ARC|BIZ|CLN|DEP|GIT|LOG|PRF|SEC|TST|UX)-\d{2,3}\b", text, re.M))
        intro = next((line.strip() for line in text.splitlines()[1:] if line.strip() and not line.startswith("#")), "")
        cards.append(f'<a class="principle-card" href="{path.stem}.html" data-card><span class="number">{path.stem[:2]}</span><h2>{html.escape(title)}</h2><p>{_inline(intro, None, set())}</p><span>{rules} rules</span></a>')
    cards.append('<a class="principle-card workflow-card" href="handover-workflow.html" data-card><span class="number">↗</span><h2>Device handover workflow</h2><p>Code-derived stages, dependencies, recovery paths and lifecycle.</p><span>10 stages</span></a>')
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><title>H-Caliper Principles</title><link rel="stylesheet" href="assets/visual.css"><script defer src="assets/visual.js"></script></head><body data-page="index"><header class="site-header"><strong>H-Caliper Principles</strong><label class="search-label">Search principles <input data-search type="search" aria-label="Search principles"></label><button type="button" data-theme>Theme</button></header><main class="index-main"><h1>Principle files</h1><p>Markdown is the source of truth. These pages are generated from it.</p><div class="cards">' + ''.join(cards) + '</div></main></body></html>'


def outputs() -> dict[Path, str]:
    sources = sorted(DOCS.glob("*.md"))
    known = _rule_ids()
    results = {OUT / f"{path.stem}.html": _page(path, known) for path in sources}
    results[OUT / "index.html"] = _index(sources)
    results[WORKFLOW_OUT] = handover_workflow_html()
    results[CSS] = VISUAL_CSS
    results[JS] = VISUAL_JS
    return results


def validate_svg_documents(documents: dict[Path, str]) -> None:
    ns = {"s": "http://www.w3.org/2000/svg"}
    for path, document in documents.items():
        if path.suffix != ".html": continue
        for svg in re.findall(r"<svg\b.*?</svg>", document, flags=re.S):
            root = ElementTree.fromstring(svg)
            for rect in root.findall(".//s:rect", ns):
                if "width" not in rect.attrib or "height" not in rect.attrib: continue
                width, height = float(rect.attrib["width"]), float(rect.attrib["height"])
                if root.attrib.get("class", "").find("stage-svg") >= 0 and width < 160: raise ValueError(f"Small stage box in {path}")
                if root.attrib.get("class", "").find("module-svg") >= 0 and (width < 160 or height < 44): raise ValueError(f"Small module box in {path}")
            for text in root.findall(".//s:text", ns):
                if int(text.attrib.get("font-size", "14")) < 14: raise ValueError(f"Small SVG label in {path}")
            for marker in root.findall(".//s:marker", ns):
                if float(marker.attrib.get("markerWidth", 0)) < 8: raise ValueError(f"Arrowhead under 8px in {path}")


def build(check: bool = False) -> bool:
    checked_contrasts()
    generated = outputs()
    validate_svg_documents(generated)
    stale = []
    for path, content in generated.items():
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content: stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    print("Contrast pairs checked (both themes):")
    for label, fg, bg, ratio in checked_contrasts(): print(f"{label} | {fg} | {bg} | {ratio:.2f}:1")
    if check:
        if stale:
            print("STALE: " + ", ".join(str(p.relative_to(ROOT)) for p in stale), file=sys.stderr)
            return False
        print(f"OK: {len(generated)} generated files are current")
    else:
        print(f"Generated {len(generated)} files")
    return True


VISUAL_CSS = """*{box-sizing:border-box}html{font:17px/1.65 system-ui,-apple-system,'Segoe UI',sans-serif;color-scheme:light dark}body{margin:0;background:#fff;color:#1f2328}a{color:#0969da}a:focus-visible,button:focus-visible,input:focus-visible,[tabindex]:focus-visible{outline:3px solid #0969da;outline-offset:3px}button,input{font:inherit}button{cursor:pointer}.site-header{position:sticky;top:0;z-index:10;display:flex;gap:14px;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid #d0d7de}.site-header strong{font-size:18px}.search-label{margin-left:auto;display:flex;gap:8px;align-items:center}.search-label input{max-width:18rem}.layout{display:grid;grid-template-columns:240px minmax(0,1fr);gap:20px;padding:16px}.full-layout{display:block;padding:16px}.toc-rail{position:fixed;top:58px;bottom:0;left:0;width:260px;overflow:auto;padding:16px;background:#f6f8fa;border-right:1px solid #d0d7de;z-index:8}.layout .toc-rail{position:sticky;top:74px;align-self:start;width:auto;max-height:calc(100vh - 90px)}.toc-rail[hidden]{display:none}.toc-rail a{display:block;padding:4px 6px;text-decoration:none;color:#1f2328}.toc-level-3{padding-left:18px!important}.principle-main{max-width:75ch;margin:0 auto;width:100%}.full-layout .principle-main{max-width:none}.principle-main>p,.principle-main>ul,.principle-main>ol,.principle-main>blockquote,.principle-main>table,.principle-main>h1,.principle-main>h2{max-width:75ch}.graph-section>h2{max-width:75ch}.principle-main h1{font-size:32px;line-height:1.2}.principle-main h2{font-size:24px;line-height:1.3}.principle-main h3{font-size:20px;line-height:1.35}.principle-main h4{font-size:18px}.generated{font-size:14px;color:#57606a}.index-main{max-width:1200px;margin:auto;padding:32px 20px}.index-main h1{font-size:32px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}.principle-card{display:block;padding:18px;border:1px solid #d0d7de;border-radius:8px;background:#f6f8fa;color:#1f2328;text-decoration:none}.principle-card h2{font-size:20px}.principle-card:hover{border-color:#0969da}.number{font:700 22px ui-monospace,monospace;color:#0969da}.rule-badge{display:inline-block;padding:0 5px;border:1px solid #57606a;border-radius:4px;font:700 14px ui-monospace,monospace;color:#1f2328;text-decoration:none}.broken-ref{color:#cf222e;text-decoration:underline wavy}.table-wrap{overflow:auto;max-width:100%;margin:16px 0}table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border:1px solid #d0d7de;text-align:left;vertical-align:top}thead{background:#f6f8fa}.code-wrap pre{overflow:auto;padding:16px;background:#f6f8fa;border:1px solid #d0d7de;border-radius:6px;font:15px/1.55 ui-monospace,Consolas,monospace}.graph-section{max-width:none;margin:48px 0}.graph-section>p{max-width:75ch}.graph-section h2{font-size:24px}.legend-sticky{position:sticky;top:54px;z-index:6;display:flex;gap:16px;flex-wrap:wrap;padding:10px 12px;background:#fff;border:1px solid #d0d7de}.diagram-scroll{overflow:auto;max-width:100%;margin:16px 0;border:0;background:#fff;cursor:grab}.diagram-scroll:active{cursor:grabbing}.graph-svg{display:block;height:auto;min-width:100%;transform-origin:top left}.layer-band rect{fill:#f6f8fa;stroke:var(--layer-color);stroke-width:2}.band-name{font:700 20px system-ui;fill:#1f2328}.band-count{font:15px system-ui;fill:#57606a}.marker{font:700 21px system-ui;fill:var(--layer-color)}.direction-label{font-weight:700}.layer-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.layer-tabs button{border:1px solid #d0d7de;border-radius:6px;padding:7px 12px;background:#f6f8fa}.layer-tabs button[aria-selected=true]{border-color:#0969da;background:#eaf2fc}.layer-detail[hidden]{display:none}.layer-detail h3{font-size:20px}.module-svg .graph-node{cursor:pointer}.module-svg .graph-node rect{fill:color-mix(in srgb,var(--node-color) 12%,#f6f8fa);stroke:var(--node-color);stroke-width:2}.module-svg .graph-node text{font:15px ui-monospace,monospace;fill:#1f2328}.graph-node.selected rect{stroke:#0969da;stroke-width:4}.graph-node.related rect{fill:#e8f4f4}.graph-node.dim{opacity:.15}.module-list{max-width:100%;columns:2;column-gap:32px}.module-list li{break-inside:avoid;padding:5px}.module-list code{font:15px ui-monospace,monospace}.module-list [data-module-row].selected{background:#eaf2fc}.graph-search{display:flex;gap:8px;align-items:center;margin:16px 0}.graph-search input{padding:6px 10px;border:1px solid #d0d7de;border-radius:6px}.graph-focus-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(280px,360px);gap:16px}.module-details{position:sticky;top:130px;align-self:start;padding:16px;background:#f6f8fa;border:1px solid #d0d7de}.module-details[hidden]{display:none}.module-details dl{display:grid;grid-template-columns:90px 1fr;gap:8px}.module-details dd{margin:0;overflow-wrap:anywhere}.stage-svg{min-width:max(100%,var(--svg-width,1px))}.stage-svg .stage-node rect{fill:#eaf2fc;stroke:#0969da;stroke-width:2}.stage-svg .stage-label,.stage-svg .stage-number,.stage-svg .stage-sub{font:15px ui-monospace,monospace;fill:#1f2328}.stage-svg .stage-number{font-weight:700}.stage-svg .stage-sub{font-size:14px}.stage-svg .edge{fill:none;stroke:#57606a;stroke-width:1.7;opacity:.15}.stage-svg .edge.related{opacity:1}.stage-svg marker path{fill:#57606a}.stage-node{cursor:pointer}.stage-node.selected rect{stroke:#0969da;stroke-width:4}.status-ok{padding:12px;border:2px solid #1a7f37;background:#f6f8fa;color:#1f2328}.status-error{border:2px solid #cf222e}.freshness{padding:10px;border-left:4px solid #1a7f37;font-weight:700}.theme-dark{background:#0f1419;color:#e6edf3}.theme-dark .site-header,.theme-dark .legend-sticky{background:#0f1419;color:#e6edf3;border-color:#30363d}.theme-dark .toc-rail,.theme-dark .principle-card,.theme-dark .layer-tabs button,.theme-dark .module-details,.theme-dark thead,.theme-dark .status-ok{background:#161b22;color:#e6edf3;border-color:#30363d}.theme-dark .toc-rail a,.theme-dark .principle-card{color:#e6edf3}.theme-dark .layer-band rect{fill:#161b22}.theme-dark .band-name,.theme-dark .module-svg .graph-node text,.theme-dark .stage-svg text{fill:#e6edf3}.theme-dark .band-count{fill:#9aa4af}.theme-dark .stage-svg .stage-node rect{fill:#161b22}.theme-dark .module-svg .graph-node rect{fill:color-mix(in srgb,var(--node-color) 22%,#161b22);stroke:var(--node-color)}.theme-dark .module-details{background:#161b22}.theme-dark .stage-svg .edge{stroke:#9aa4af}.theme-dark .stage-svg marker path{fill:#9aa4af}.theme-dark .status-ok{color:#e6edf3}.theme-dark .rule-badge{background:#161b22;color:#e6edf3}@media(max-width:800px){.layout{display:block}.layout .toc-rail{position:static;max-height:30vh;margin-bottom:12px}.full-layout{padding:8px}.graph-focus-layout{grid-template-columns:1fr}.module-details{position:static}.module-list{columns:1}.site-header{flex-wrap:wrap}.search-label{margin-left:0}}@media print{@page{size:landscape;margin:12mm}.site-header,.toc-rail,.search-label,button,.graph-search{display:none!important}.graph-section{break-before:page;page-break-before:always}.diagram-scroll{overflow:visible}.graph-svg{min-width:0;width:auto}.module-details{position:static}.layout{display:block}.principle-main{max-width:none}}"""

VISUAL_JS = """(()=>{'use strict';const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];const body=document.body;let mode='';try{mode=localStorage.getItem('principles-theme')||''}catch{}if(mode==='dark')body.classList.add('theme-dark');if(mode==='light')body.classList.add('theme-light');$$('[data-theme]').forEach(b=>b.addEventListener('click',()=>{const dark=body.classList.contains('theme-dark')||(!body.classList.contains('theme-light')&&matchMedia('(prefers-color-scheme: dark)').matches);body.classList.toggle('theme-dark',!dark);body.classList.toggle('theme-light',dark);try{localStorage.setItem('principles-theme',dark?'light':'dark')}catch{}}));const rail=$('.toc-rail');$$('[data-toggle-rail]').forEach(b=>b.addEventListener('click',()=>{if(!rail)return;rail.hidden=!rail.hidden;b.setAttribute('aria-expanded',String(!rail.hidden));b.textContent=rail.hidden?'Show contents':'Hide contents';try{localStorage.setItem('principles-rail-hidden',String(rail.hidden))}catch{}}));try{if(localStorage.getItem('principles-rail-hidden')==='true'&&rail){rail.hidden=true;$$('[data-toggle-rail]').forEach(b=>{b.setAttribute('aria-expanded','false');b.textContent='Show contents'})}}catch{}const search=$('[data-search]');search?.addEventListener('input',()=>{const q=search.value.toLocaleLowerCase();if(body.dataset.page==='index')$$('[data-card]').forEach(c=>c.hidden=!c.innerText.toLocaleLowerCase().includes(q));else $$('main h2').forEach(h=>{let rows=[h];for(let n=h.nextElementSibling;n&&!/^H2$/.test(n.tagName);n=n.nextElementSibling)rows.push(n);const match=rows.some(x=>x.innerText?.toLocaleLowerCase().includes(q));rows.forEach(x=>x.hidden=!!q&&!match)})});$$('[data-layer-tab]').forEach(tab=>tab.addEventListener('click',()=>{$$('[data-layer-tab]').forEach(x=>x.setAttribute('aria-selected',String(x===tab)));$$('[data-layer-panel]').forEach(p=>p.hidden=p.dataset.layerPanel!==tab.dataset.layerTab)}));const modules=$$('.graph-node[data-module]'),detail=$('[data-module-details]'),empty=$('[data-focus-empty]');function focus(node){const id=node.dataset.module,imports=(node.dataset.imports||'').split('|').filter(Boolean),importers=(node.dataset.importers||'').split('|').filter(Boolean),near=new Set([id,...imports,...importers]);modules.forEach(n=>{n.classList.toggle('selected',n.dataset.module===id);n.classList.toggle('related',near.has(n.dataset.module)&&n.dataset.module!==id);n.classList.toggle('dim',!near.has(n.dataset.module))});$$('[data-module-row]').forEach(r=>{r.classList.toggle('selected',r.dataset.moduleRow===id);r.hidden=!near.has(r.dataset.moduleRow)});if(detail){detail.hidden=false;empty.hidden=true;$('[data-detail-name]').textContent=node.querySelector('title')?.textContent.split(' — ')[0]||id;$('[data-detail-layer]').textContent=node.dataset.layer;$('[data-detail-path]').textContent=id;$('[data-detail-lines]').textContent=node.dataset.lines;$('[data-detail-imports]').textContent=imports.join(', ')||'None';$('[data-detail-importers]').textContent=importers.join(', ')||'None'}}modules.forEach(n=>{n.addEventListener('click',()=>focus(n));n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();focus(n)}if(e.key==='Escape'){modules.forEach(x=>x.classList.remove('selected','related','dim'));$$('[data-module-row]').forEach(x=>x.hidden=false);if(detail)detail.hidden=true;if(empty)empty.hidden=false}})});const moduleSearch=$('[data-module-search]');moduleSearch?.addEventListener('input',()=>{const q=moduleSearch.value.toLowerCase();modules.forEach(n=>{const show=n.dataset.module.toLowerCase().includes(q)||n.querySelector('title').textContent.toLowerCase().includes(q);n.style.opacity=show?'1':'.15'})});$$('[data-module-row]').forEach(row=>row.addEventListener('click',()=>{const n=modules.find(x=>x.dataset.module===row.dataset.moduleRow);if(n){const tab=$(`[data-layer-tab="${n.dataset.layer}"]`);tab?.click();focus(n)}}));$$('.stage-node').forEach(n=>{const activate=()=>{$$('.stage-node').forEach(x=>x.classList.toggle('selected',x===n));$$('.stage-svg .edge').forEach(e=>e.classList.toggle('related',e.dataset.source===n.dataset.stage||e.dataset.target===n.dataset.stage))};n.addEventListener('click',activate);n.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();activate()}if(e.key==='Escape')$$('.stage-node').forEach(x=>x.classList.remove('selected'))})});$$('.diagram-scroll').forEach(z=>{const svg=$('svg',z);if(!svg)return;let scale=1;const base=Number(svg.getAttribute('width'))||svg.getBoundingClientRect().width;const apply=()=>{svg.style.width=`${base*scale}px`;svg.style.minWidth='0'};const bar=document.createElement('div');bar.className='zoom-controls';[['+',.15],['−',-.15],['Fit',-1],['100%',-2]].forEach(([label,delta])=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.setAttribute('aria-label',label==='Fit'?'Fit diagram to width':label==='100%'?'Show diagram at 100%':`Zoom ${label}`);b.addEventListener('click',()=>{if(delta===-1)scale=Math.max(1,z.clientWidth/base);else if(delta===-2)scale=1;else scale=Math.max(1,Math.min(2.5,scale+delta));apply()});bar.append(b)});z.before(bar);scale=Math.max(1,z.clientWidth/base);apply();z.addEventListener('wheel',e=>{if(e.ctrlKey){e.preventDefault();scale=Math.max(1,Math.min(2.5,scale+(e.deltaY<0?.08:-.08)));apply()}},{passive:false});let drag=null;z.addEventListener('pointerdown',e=>{if(e.target.closest('g'))return;drag=[e.clientX,z.scrollLeft];z.setPointerCapture(e.pointerId)});z.addEventListener('pointermove',e=>{if(drag)z.scrollLeft=drag[1]-(e.clientX-drag[0])});z.addEventListener('pointerup',()=>drag=null)});})();"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return 0 if build(args.check) else 1


if __name__ == "__main__":
    raise SystemExit(main())
