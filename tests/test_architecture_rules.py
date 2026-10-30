"""Enforces the layered-architecture dependency rules (ARC-01, ARC-04, ARC-05).

The checks are directory-driven and skip packages that do not exist yet, so the
test is meaningful at every phase of the build-out. New code that violates the
rules fails here instead of being caught in review.
"""

import ast
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
REPO_ROOT = APP_DIR.parent

# Legacy exemption, not a precedent: app/routers/snipeit.py speaks HTTP
# directly today. Phase 3 moves all Snipe-IT HTTP into app/clients/snipeit.py
# and deletes this entry; the guard below fails if the entry goes stale.
LEGACY_HTTP_ROUTERS = {"app/routers/snipeit.py"}


def _python_files(package: str) -> list[Path]:
    """Every non-``__init__`` Python file under ``app/<package>``, if it exists."""
    directory = APP_DIR / package
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*.py") if p.name != "__init__.py")


def _imported_modules(path: Path) -> set[str]:
    """Absolute module names imported by ``path`` (relative imports excluded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def _relative(path: Path) -> str:
    return path.relative_to(APP_DIR.parent).as_posix()


@pytest.mark.parametrize("path", _python_files("domain"), ids=_relative)
def test_domain_imports_standard_library_only(path: Path) -> None:
    """ARC-01: ``app/domain`` is pure Python and imports nothing from the app."""
    offenders = []
    for module in _imported_modules(path):
        root = module.split(".")[0]
        if module.startswith("app") or root not in sys.stdlib_module_names:
            offenders.append(module)
    assert not offenders, f"{_relative(path)} imports non-stdlib modules: {offenders}"


@pytest.mark.parametrize("path", _python_files("routers"), ids=_relative)
def test_routers_do_not_import_db_or_httpx(path: Path) -> None:
    """ARC-05: routers talk to services, never to the database or HTTP clients."""
    if _relative(path) in LEGACY_HTTP_ROUTERS:
        pytest.skip("legacy: Snipe-IT HTTP moves to app/clients in Phase 3")
    forbidden = ("app.db", "httpx")
    offenders = [
        module
        for module in _imported_modules(path)
        if module == forbidden[0]
        or module.startswith(forbidden[0] + ".")
        or module == forbidden[1]
        or module.startswith(forbidden[1] + ".")
    ]
    assert not offenders, f"{_relative(path)} imports forbidden modules: {offenders}"


def test_legacy_http_router_exemptions_are_still_needed() -> None:
    """An exemption must be removed in the same change that fixes the file."""
    for relative in LEGACY_HTTP_ROUTERS:
        path = REPO_ROOT / relative
        assert path.is_file(), f"stale exemption: {relative} no longer exists"
        imports = _imported_modules(path)
        assert any(m == "httpx" or m.startswith("httpx.") for m in imports), (
            f"stale exemption: {relative} no longer imports httpx; delete it"
        )


@pytest.mark.parametrize("path", _python_files("services"), ids=_relative)
def test_services_do_not_import_fastapi(path: Path) -> None:
    """ARC-04: services raise domain exceptions; routers map them to HTTP."""
    offenders = [
        module
        for module in _imported_modules(path)
        if module == "fastapi" or module.startswith("fastapi.")
    ]
    assert not offenders, f"{_relative(path)} imports fastapi: {offenders}"
