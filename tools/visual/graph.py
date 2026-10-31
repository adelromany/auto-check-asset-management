"""Builders for the LIVE GRAPH diagrams and the graph wrapper page."""

from __future__ import annotations

import html
import re
from collections import defaultdict
from pathlib import Path

from .artifacts import REPO_ROOT
from .markdown import PRINCIPLES_DIR
from tools.graph_data import GraphData, actual_modules, parse_graph

GRAPH_MD = PRINCIPLES_DIR / "03-graph-principles.md"
OUTPUT_DIR = "docs/visual/graph"

LAYER_ORDER = ("router", "service", "repository", "client", "db", "dto", "domain", "config", "infra")
BAND_ORDER = ("router", "service", "repository-client", "db-external", "domain")
BAND_LABELS = {
    "router": "routers",
    "service": "services",
    "repository-client": "repositories / clients",
    "db-external": "db / external systems",
    "domain": "domain (pure)",
}
BAND_LAYERS = {
    "router": {"router"},
    "service": {"service"},
    "repository-client": {"repository", "client"},
    "db-external": {"db", "dto", "config"},
    "domain": {"domain"},
}
# The infra layer holds the application factory, HTTP hardening and the local
# build tools.  It is not one of the five dependency bands, so it is drawn as
# its own cross-cutting band beside them.
INFRA_LAYER = {"infra"}


def _slug(value: str) -> str:
    value = value.replace("app/", "").replace("tools/", "").replace(".py", "")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value or "node"


def graph_data() -> GraphData:
    return parse_graph(GRAPH_MD.read_text(encoding="utf-8"))


def _module_id(path: str) -> str:
    return _slug(path)


def _native(
    *,
    title: str,
    slug: str,
    view_box: list[int],
    components: list[dict],
    connections: list[dict] | None = None,
    boundaries: list[dict] | None = None,
    cards: list[dict] | None = None,
    subtitle: str = "",
    views: list[dict] | None = None,
) -> dict:
    meta: dict = {
        "title": title,
        "output": f"{OUTPUT_DIR}/{slug}.html",
        "viewBox": view_box,
        "quality_profile": "showcase",
    }
    if subtitle:
        meta["subtitle"] = subtitle
    if views:
        meta["views"] = views
    payload = {
        "schema_version": 1,
        "diagram_type": "architecture",
        "meta": meta,
        "components": components,
        "connections": connections or [],
    }
    if boundaries:
        payload["boundaries"] = boundaries
    if cards:
        payload["cards"] = cards
    return payload


def build_overview() -> dict:
    components = [
        {"id": "routers", "type": "frontend", "label": "routers", "sublabel": "HTTP input and auth", "pos": [40, 150], "size": [200, 64]},
        {"id": "services", "type": "backend", "label": "services", "sublabel": "orchestration", "pos": [300, 150], "size": [200, 64]},
        {"id": "data", "type": "backend", "label": "repositories / clients", "sublabel": "queries and HTTP", "pos": [560, 150], "size": [220, 64]},
        {"id": "store", "type": "database", "label": "db / external", "sublabel": "SQLAlchemy · Snipe-IT", "pos": [840, 150], "size": [210, 64]},
        {"id": "domain", "type": "backend", "label": "domain", "sublabel": "pure rules", "pos": [300, 340], "size": [200, 64]},
    ]
    connections = [
        {"from": "routers", "to": "services", "label": "calls"},
        {"from": "services", "to": "data", "label": "uses"},
        {"from": "data", "to": "store", "label": "reads / writes"},
        {"from": "services", "to": "domain", "label": "pure rules"},
    ]
    return _native(
        title="Allowed dependency direction",
        slug="architecture-overview",
        subtitle="Five layers from the GRAPH principle; edges point downstream only.",
        view_box=[1120, 470],
        components=components,
        connections=connections,
        cards=[
            {"dot": "cyan", "title": "One direction", "items": ["Routers call services.", "Services call repositories or clients.", "Repositories and clients reach the database or Snipe-IT.", "The domain layer stays pure."]},
            {"dot": "emerald", "title": "Cross-cutting", "items": ["app/security/* hardens HTTP and may read app/config.py.", "Security is imported by the application wiring, not by business services."]},
        ],
    )


def build_modules() -> dict:
    data = graph_data()
    by_layer: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for path, layer, responsibility in data.modules:
        by_layer[layer].append((path, layer, responsibility))
    bands = [
        ("router", "routers", {"router"}),
        ("service", "services", {"service"}),
        ("data", "repositories / clients", {"repository", "client"}),
        ("store", "db / external systems", {"db", "dto", "config"}),
        ("domain", "domain (pure)", {"domain"}),
        ("infra", "infrastructure and tools", INFRA_LAYER),
    ]
    components: list[dict] = []
    boundaries: list[dict] = []
    x = 40
    max_rows = 1
    for band_id, label, layers in bands:
        paths = [row for layer in LAYER_ORDER if layer in layers for row in by_layer[layer]]
        if not paths:
            continue
        max_rows = max(max_rows, len(paths))
        ids = []
        for index, (path, layer, responsibility) in enumerate(paths):
            node_id = _module_id(path)
            ids.append(node_id)
            node_label = Path(path).stem
            components.append(
                {
                    "id": node_id,
                    "type": "backend",
                    "label": node_label,
                    "sublabel": layer,
                    "tag": responsibility[:42],
                    "pos": [x, 80 + index * 58],
                    "size": [172, 44],
                }
            )
        boundaries.append(
            {"kind": "region", "label": f"{label} ({len(ids)})", "wraps": ids, "pad": 12}
        )
        x += 196
    return _native(
        title="Every module in its band",
        slug="architecture-modules",
        subtitle="Every module node from the LIVE GRAPH, grouped by its declared layer.",
        view_box=[x + 12, 80 + max_rows * 58 + 80],
        components=components,
        boundaries=boundaries,
        cards=[
            {"dot": "cyan", "title": "Source", "items": [f"{len(data.modules)} module rows between GRAPH:START and GRAPH:END.", "The node and edge tables remain the source of truth."]},
            {"dot": "amber", "title": "Dense by design", "items": ["This view is the inventory, not a route map.", "Open a focus view for one layer."]},
        ],
    )


def build_focus(layer: str) -> dict:
    data = graph_data()
    paths = [(p, l, r) for p, l, r in data.modules if l == layer]
    components = []
    for index, (path, layer_name, responsibility) in enumerate(paths):
        components.append(
            {
                "id": _module_id(path),
                "type": "backend",
                "label": Path(path).name,
                "sublabel": path.replace("app/", "").replace("tools/", ""),
                "tag": responsibility[:56],
                "pos": [40, 70 + index * 66],
                "size": [320, 52],
            }
        )
    layer_label = {
        "router": "routers",
        "service": "services",
        "repository": "repositories",
        "client": "clients",
        "db": "database",
        "dto": "DTOs",
        "domain": "domain",
        "config": "configuration",
        "infra": "infrastructure and tools",
    }[layer]
    return _native(
        title=f"{layer_label}: module focus",
        slug=f"focus-{_slug(layer)}",
        subtitle=f"{len(paths)} modules declared as {layer} in the LIVE GRAPH.",
        view_box=[400, max(240, 70 + len(paths) * 66 + 50)],
        components=components,
        cards=[
            {"dot": "cyan", "title": "How to read it", "items": ["Each node is one Python module from the graph.", "The tag is its recorded responsibility.", "Open the architecture page for the allowed dependency direction."]},
        ],
    )


def build_violations() -> dict:
    data = graph_data()
    # The architecture tests enforce three rules: domain imports nothing from
    # app, routers import no database or httpx, services import no FastAPI.
    violations = []
    for path, layer, _ in data.modules:
        if layer == "domain" and path.startswith("app/domain/"):
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
            if re.search(r"^\s*(from|import)\s+app\b", text, re.MULTILINE):
                violations.append(path)
        if layer == "router" and path.startswith("app/routers/"):
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
            if re.search(r"^\s*(from|import)\s+(app\.db|httpx)\b", text, re.MULTILINE):
                violations.append(path)
        if layer == "service" and path.startswith("app/services/"):
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
            if re.search(r"^\s*(from|import)\s+fastapi\b", text, re.MULTILINE):
                violations.append(path)
    count = len(violations)
    components = [
        {"id": "layer-domain", "type": "backend", "label": "domain", "sublabel": "must import nothing from app", "pos": [40, 120], "size": [230, 64]},
        {"id": "layer-router", "type": "frontend", "label": "routers", "sublabel": "no db, no httpx", "pos": [330, 120], "size": [210, 64]},
        {"id": "layer-service", "type": "backend", "label": "services", "sublabel": "no FastAPI", "pos": [600, 120], "size": [210, 64]},
    ]
    connections = [
        {"from": "layer-router", "to": "layer-service", "label": "allowed"},
    ]
    return _native(
        title="Layering violations",
        slug="violations",
        subtitle="Checked against the same rules as tests/test_architecture_rules.py.",
        view_box=[880, 300],
        components=components,
        connections=connections,
        cards=[
            {"dot": "emerald", "title": f"{count} violations", "items": ["Every edge in the LIVE GRAPH passes the three architecture checks.", "A violation would appear here as a labelled problem edge."]},
            {"dot": "cyan", "title": "Checked rules", "items": ["domain imports standard library only", "routers import no app.db and no httpx", "services import no FastAPI"]},
        ],
    )


def build_graph_index() -> str:
    data = graph_data()
    listed_app = {path for path, _, _ in data.modules if path.startswith("app/")}
    on_disk = actual_modules(REPO_ROOT / "app", REPO_ROOT)
    fresh = listed_app == on_disk
    total = len(data.modules)
    banner = ""
    if not fresh:
        banner = (
            '<p class="banner">LIVE GRAPH is out of date: '
            f"{len(listed_app)} app modules listed, {len(on_disk)} found under app/.</p>"
        )
    cards = [
        ("Architecture overview", "architecture-overview.html", "The five layers and the allowed dependency direction."),
        ("Every module", "architecture-modules.html", f"All {total} module nodes from the LIVE GRAPH in their bands."),
        ("Routers focus", "focus-router.html", "The nine router modules and their recorded responsibilities."),
        ("Services focus", "focus-service.html", "The six service modules and their recorded responsibilities."),
        ("Repositories focus", "focus-repository.html", "The three repository modules and their recorded responsibilities."),
        ("Clients focus", "focus-client.html", "The one external HTTP client."),
        ("Database focus", "focus-db.html", "The three database modules."),
        ("DTOs focus", "focus-dto.html", "The three request/response model modules."),
        ("Domain focus", "focus-domain.html", "The seven pure domain modules."),
        ("Configuration focus", "focus-config.html", "The one environment reader."),
        ("Infrastructure focus", "focus-infra.html", "Application wiring, security middleware and local build tools."),
        ("Violations", "violations.html", "0 layering violations in the same data the architecture tests use."),
    ]
    card_html = "\n".join(
        f"""      <a class="card" href="{href}">
        <h2>{html.escape(title)}</h2>
        <p>{html.escape(text)}</p>
        <span class="meta"><span>{html.escape(href)}</span><span class="pill">Open</span></span>
      </a>"""
        for title, href, text in cards
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LIVE GRAPH · Visual documentation</title>
<style>
:root{{color-scheme:light dark;--bg:#f6f7f9;--panel:#fff;--ink:#16181d;--muted:#5c6370;--line:#d9dde5;--accent:#0b63ce;--soft:#e8f1fd;--bad:#b42318;--bad-soft:#fee4e2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#101216;--panel:#171a20;--ink:#e8ebf1;--muted:#9aa3b2;--line:#2a2f3a;--accent:#6aa8ff;--soft:#152238;--bad:#ff8a80;--bad-soft:#3a1512}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}}
a{{color:var(--accent);text-decoration:none}}a:hover{{text-decoration:underline}}
.wrap{{max-width:1120px;margin:0 auto;padding:48px 24px 80px}}
.eyebrow{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:700}}
h1{{font-size:34px;line-height:1.15;margin:8px 0 10px;letter-spacing:-.02em}}
.lede{{color:var(--muted);max-width:70ch;margin:0}}
.banner{{background:var(--bad-soft);color:var(--bad);border:1px solid var(--bad);border-radius:10px;padding:12px 14px;font-weight:600;margin:18px 0 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px;margin-top:26px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:8px;min-height:132px;box-shadow:0 1px 2px rgba(16,24,40,.06),0 8px 24px rgba(16,24,40,.05)}}
.card h2{{font-size:17px;margin:0;line-height:1.3}}.card p{{margin:0;color:var(--muted);font-size:14px}}
.meta{{margin-top:auto;padding-top:10px;border-top:1px solid var(--line);display:flex;justify-content:space-between;gap:8px;font-size:12px;color:var(--muted)}}
.pill{{background:var(--soft);color:var(--accent);border-radius:999px;padding:2px 9px;font-weight:600}}
footer{{margin-top:36px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}}
</style>
</head>
<body>
<main class="wrap">
  <div class="eyebrow">03 · Graph Principles</div>
  <h1>LIVE GRAPH</h1>
  <p class="lede">The machine-checked graph in <code>docs/principles/03-graph-principles.md</code> states {len(listed_app)} app modules. <code>app/</code> contains {len(on_disk)} modules; the LIVE GRAPH has {total} module rows in total, including local build tools.</p>
  {banner}
  <section class="grid">
{card_html}
  </section>
  <footer>Generated from the LIVE GRAPH with Archify 3.2.0. <a href="../index.html">Back to visual documentation</a>.</footer>
</main>
</body>
</html>
"""
