"""Shared parsing for the machine-checked LIVE GRAPH section."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GraphData:
    modules: list[tuple[str, str, str]]
    imports: list[tuple[str, str]]
    stages: list[tuple[str, str]]


def graph_section(text: str) -> str:
    """Return text strictly between standalone GRAPH markers."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "<!-- GRAPH:START -->")
    end = next(i for i, line in enumerate(lines) if line.strip() == "<!-- GRAPH:END -->")
    return "\n".join(lines[start + 1:end])


def module_rows(section: str) -> list[tuple[str, str]]:
    """Match the original graph test's exact module-row parsing rules."""
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 4 and cells[0] == "module":
            rows.append((cells[1], cells[2]))
    return rows


def parse_graph(text: str) -> GraphData:
    section = graph_section(text)
    modules = []
    imports = []
    stages = []
    for path, layer in module_rows(section):
        responsibility = ""
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) >= 4 and cells[0] == "module" and cells[1] == path:
                responsibility = cells[3]
                break
        modules.append((path, layer, responsibility))
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 3 and cells[1] == "imports":
            imports.append((cells[0], cells[2]))
        if len(cells) >= 3 and cells[0] == "stage":
            stages.append((cells[1], cells[2]))
    return GraphData(modules, imports, stages)


def actual_modules(app_dir: Path, repo_root: Path) -> set[str]:
    """Reuse graph consistency's definition of real app modules."""
    return {
        path.relative_to(repo_root).as_posix()
        for path in app_dir.rglob("*.py")
        if path.name != "__init__.py"
    }
