"""Hard size, contrast and offline guarantees for generated architecture SVGs."""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree

from tools.build_principles_visual import checked_contrasts, outputs, validate_svg_documents
from app.domain.stages import STAGE_DEPENDENCIES, STAGE_ORDER

SVG_NS = {"s": "http://www.w3.org/2000/svg"}
ROOT = Path(__file__).resolve().parents[1]


def test_generated_svg_nodes_arrows_and_spacing_meet_minimums() -> None:
    documents = outputs()
    validate_svg_documents(documents)
    graph = documents[ROOT / "docs/principles/visual/03-graph-principles.html"]
    svgs = [ElementTree.fromstring(raw) for raw in re.findall(r"<svg\b.*?</svg>", graph, re.S)]
    assert svgs
    for svg in svgs:
        classes = svg.attrib.get("class", "")
        if "overview-svg" in classes:
            bands = svg.findall(".//s:g[@class='layer-band']/s:rect", SVG_NS)
            ys = sorted(float(node.attrib["y"]) for node in bands)
            heights = [float(node.attrib["height"]) for node in bands]
            assert all(ys[i + 1] - (ys[i] + heights[i]) >= 90 for i in range(len(ys) - 1))
        if "module-svg" in classes:
            rects = [g.find("s:rect", SVG_NS) for g in svg.findall(".//s:g[@class='graph-node']", SVG_NS)]
            assert all(float(r.attrib["width"]) >= 160 and float(r.attrib["height"]) >= 44 for r in rects if r is not None)
            positions = sorted((float(r.attrib["x"]), float(r.attrib["y"])) for r in rects if r is not None)
            for x, y in positions:
                for other_x, other_y in positions:
                    if other_y == y and other_x > x:
                        assert other_x - (x + 260) >= 24
                        break
        if "stage-svg" in classes:
            rects = [g.find("s:rect", SVG_NS) for g in svg.findall(".//s:g[@class='stage-node']", SVG_NS)]
            assert len(rects) == 10
            nodes = [n.attrib["data-stage"] for n in svg.findall(".//s:g[@class='stage-node']", SVG_NS)]
            assert nodes == [stage.value for stage in STAGE_ORDER]
            edges = {(e.attrib["data-source"], e.attrib["data-target"]) for e in svg.findall(".//s:path[@class='edge']", SVG_NS)}
            assert edges == {(stage.value, dep.value) for stage in STAGE_ORDER for dep in STAGE_DEPENDENCIES[stage]}
            assert all(float(r.attrib["width"]) >= 160 and float(r.attrib["height"]) >= 44 for r in rects if r is not None)
            assert all(float(m.attrib["markerWidth"]) >= 8 for m in svg.findall(".//s:marker", SVG_NS))
            assert all(float(p.attrib["stroke-width"]) >= 1.5 for p in svg.findall(".//s:path[@class='edge']", SVG_NS))
            labels = svg.findall(".//s:text", SVG_NS)
            assert labels and all(int(t.attrib.get("font-size", "14")) >= 14 for t in labels)


def test_contrast_pairs_pass_and_both_themes_are_present() -> None:
    pairs = checked_contrasts()
    assert any("light" in name for name, *_ in pairs)
    assert any("dark" in name for name, *_ in pairs)
    assert all(ratio >= (3 if any(x in name for x in ("routers", "services", "repositories", "db", "domain", "icon")) else 4.5)
               for name, _, _, ratio in pairs)


def test_generated_pages_are_offline_and_have_native_keyboard_controls() -> None:
    graph = outputs()[ROOT / "docs/principles/visual/03-graph-principles.html"]
    assert not re.search(r'(?:href|src)=["\']https?://', graph)
    assert 'role="tab"' in graph and 'tabindex="0"' in graph
    assert "data-toggle-rail" in graph
    assert "principles-rail-hidden" in outputs()[ROOT / "docs/principles/visual/assets/visual.js"]

