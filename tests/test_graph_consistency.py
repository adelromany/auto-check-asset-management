"""Keeps the LIVE GRAPH in ``docs/principles/03-graph-principles.md`` honest.

See the specification in that file: every ``module`` row must point at a file
that exists, every ``app/**/*.py`` (except ``__init__``) must be listed, and the
declared layer must match the module's directory.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GRAPH_FILE = REPO_ROOT / "docs" / "principles" / "03-graph-principles.md"
APP_DIR = REPO_ROOT / "app"

_LAYER_BY_DIRECTORY = {
    "routers": "router",
    "services": "service",
    "repositories": "repository",
    "clients": "client",
    "domain": "domain",
    "db": "db",
    "dto": "dto",
}


def _graph_section() -> str:
    """Lines strictly between the standalone GRAPH markers.

    The markers also appear inside the specification text above the graph, so
    they must be matched as whole lines, not as substrings.
    """
    lines = GRAPH_FILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "<!-- GRAPH:START -->")
    end = next(i for i, line in enumerate(lines) if line.strip() == "<!-- GRAPH:END -->")
    return "\n".join(lines[start + 1:end])


def _module_rows() -> list[tuple[str, str]]:
    """``(path, layer)`` for every ``| module | ... |`` row in the graph."""
    rows: list[tuple[str, str]] = []
    for line in _graph_section().splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 4 and cells[0] == "module":
            rows.append((cells[1], cells[2]))
    return rows


def _actual_modules() -> set[str]:
    return {
        path.relative_to(REPO_ROOT).as_posix()
        for path in APP_DIR.rglob("*.py")
        if path.name != "__init__.py"
    }


def _expected_layers(path: str) -> set[str]:
    parts = Path(path).parts
    if len(parts) >= 3:
        layer = _LAYER_BY_DIRECTORY.get(parts[1])
        if layer:
            return {layer}
    if path == "app/config.py":
        return {"config"}
    if path == "app/schemas.py":
        return {"dto"}
    return {"config", "infra"}


def test_every_listed_module_exists() -> None:
    missing = [path for path, _ in _module_rows() if not (REPO_ROOT / path).is_file()]
    assert not missing, f"graph lists modules that do not exist: {missing}"


def test_every_module_is_listed() -> None:
    listed = {path for path, _ in _module_rows()}
    unlisted = sorted(_actual_modules() - listed)
    assert not unlisted, f"modules missing from the LIVE GRAPH: {unlisted}"


@pytest.mark.parametrize("path,layer", _module_rows(), ids=[p for p, _ in _module_rows()])
def test_declared_layer_matches_directory(path: str, layer: str) -> None:
    assert layer in _expected_layers(path), (
        f"{path} is declared as '{layer}', expected one of {_expected_layers(path)}"
    )
