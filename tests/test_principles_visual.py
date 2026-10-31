"""Tests for the standard-library principle visual generator."""

from tools.build_principles_visual import (
    extract_graph,
    markdown_to_html,
    parse_stages,
)
from pathlib import Path
import subprocess
import sys


def test_markdown_headings_tables_and_code_fences() -> None:
    rendered = markdown_to_html("# Title\n\n| A | B |\n|---|---|\n| x | y |\n\n```py\nx = 1\n```")
    assert '<h1 id="title" dir="auto">Title</h1>' in rendered.html
    assert "<table>" in rendered.html and '<th scope="col" dir="auto">A</th>' in rendered.html
    assert '<pre dir="auto"><code class="language-py">x = 1' in rendered.html


def test_markdown_nested_lists_and_checklists() -> None:
    rendered = markdown_to_html("- [ ] parent\n  - child\n    1. nested")
    assert 'type="checkbox"' in rendered.html
    assert "<ul>" in rendered.html and "<ol>" in rendered.html


def test_markdown_escapes_html_and_links_rule_ids() -> None:
    rendered = markdown_to_html("<script>alert(1)</script> SEC-007")
    assert "&lt;script&gt;" in rendered.html
    assert "<script>alert" not in rendered.html
    assert 'href="#SEC-007"' in rendered.html


def test_markdown_reports_broken_rule_references() -> None:
    rendered = markdown_to_html("SEC-007", known_rule_ids=set())
    assert "SEC-007" in rendered.broken_references


def test_graph_and_stage_extraction_fixture() -> None:
    graph = """<!-- GRAPH:START -->
| kind | path | layer | responsibility |
| module | app/a.py | router | a |
| from | edge | to |
| app/a.py | imports | app/b.py |
<!-- GRAPH:END -->"""
    parsed = extract_graph(graph)
    assert parsed.modules == [("app/a.py", "router", "a")]
    assert parsed.imports == [("app/a.py", "app/b.py")]

    stages = '''class Stage(StrEnum):\n    FIRST = "first"\n    SECOND = "second"\nSTAGE_ORDER = (Stage.FIRST, Stage.SECOND)\nSTAGE_DEPENDENCIES = {Stage.FIRST: (), Stage.SECOND: (Stage.FIRST,)}'''
    assert parse_stages(stages) == (["first", "second"], [("second", "first")])


def test_committed_visuals_match_generator() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tools/build_principles_visual.py", "--check"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
