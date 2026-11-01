"""Tests for the deterministic Archify source builders.

The source-rebuild assertions always run.  Archify validation only runs when
the pinned development tool is present; otherwise the test is skipped with a
reason instead of silently passing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.visual import archify
from tools.visual.artifacts import MANIFEST_PATH, sha256_bytes, sha256_text
from tools.visual.registry import ARTIFACTS as REGISTERED

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_registry_entries_are_unique() -> None:
    keys = [artifact.key for artifact in REGISTERED]
    outputs = [artifact.output_name for artifact in REGISTERED]
    assert len(keys) == len(set(keys)), "artifact keys must be unique"
    assert len(outputs) == len(set(outputs)), "artifact outputs must be unique"


@pytest.mark.parametrize("artifact", REGISTERED, ids=[a.key for a in REGISTERED])
def test_source_is_deterministic(artifact) -> None:
    first = artifact.source_text()
    second = artifact.source_text()
    assert first == second, f"{artifact.key}: builder is not deterministic"
    if artifact.source_path is not None:
        assert artifact.source_path.is_file(), (
            f"{artifact.source_name}: missing; run python tools/visual/build_visuals.py build"
        )
        committed = artifact.source_path.read_text(encoding="utf-8")
        assert committed == first, (
            f"{artifact.source_name}: differs from its builder; "
            "run the visual build and commit the regenerated source"
        )


@pytest.mark.parametrize("artifact", REGISTERED, ids=[a.key for a in REGISTERED])
def test_static_page_matches_builder(artifact) -> None:
    if not artifact.static:
        pytest.skip("not a static page")
    assert artifact.output_path.is_file(), (
        f"{artifact.output_name}: missing; run the visual build"
    )
    assert (
        artifact.output_path.read_text(encoding="utf-8") == artifact.source_text()
    ), f"{artifact.output_name}: differs from its builder"


@pytest.mark.parametrize(
    "artifact",
    [a for a in REGISTERED if a.diagram_type != "explainer" and not a.static],
    ids=[a.key for a in REGISTERED if a.diagram_type != "explainer" and not a.static],
)
def test_native_source_is_valid_json(artifact) -> None:
    payload = json.loads(artifact.source_text())
    assert payload["diagram_type"] == artifact.diagram_type
    # Graph artifacts use schema 1; workflow v2 and lifecycle v3 are the
    # current Archify schemas and must not be forced back to v1.
    assert payload["schema_version"] in {1, 2, 3}
    # Archify resolves the durable meta.output from the working directory
    # (the repository root), while output_name is relative to docs/visual.
    assert payload["meta"]["output"] == f"docs/visual/{artifact.output_name}"


@pytest.mark.parametrize(
    "artifact",
    [a for a in REGISTERED if a.diagram_type == "explainer"],
    ids=[a.key for a in REGISTERED if a.diagram_type == "explainer"],
)
def test_explainer_declares_english_locale(artifact) -> None:
    """Archify defaults to Chinese chrome; the task requires English pages."""
    assert artifact.source_text().startswith("@meta locale=en\n")


def test_manifest_records_every_artifact() -> None:
    if not MANIFEST_PATH.is_file():
        pytest.skip("manifest not built yet; run python tools/visual/build_visuals.py build")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["generator"]["name"] == "Archify"
    assert manifest["generator"]["version"] == archify.PINNED_VERSION
    assert manifest["generator"]["commit"] == archify.PINNED_COMMIT
    entries = {entry["html"]: entry for entry in manifest["artifacts"]}
    assert set(entries) == {artifact.output_name for artifact in REGISTERED}
    for artifact in REGISTERED:
        entry = entries[artifact.output_name]
        assert artifact.output_path.is_file()
        assert entry["html_sha256"] == sha256_bytes(
            artifact.output_path.read_bytes()
        )
        if artifact.static:
            assert entry["source"] is None
        else:
            assert entry["source_sha256"] == sha256_text(artifact.source_text())


@pytest.mark.skipif(
    not archify.available(),
    reason="Archify is not fetched; run scripts/fetch_archify.sh",
)
@pytest.mark.parametrize(
    "artifact",
    [a for a in REGISTERED if not a.static],
    ids=[a.key for a in REGISTERED if not a.static],
)
def test_source_passes_archify_showcase(artifact) -> None:
    assert artifact.source_path is not None
    receipt = archify.validate(
        artifact.diagram_type,
        REPO_ROOT / "docs" / "visual" / artifact.source_name,
        quality="showcase",
        writing="off",
    )
    assert not archify.problems(receipt), archify.problems(receipt)
    assert not receipt.get("_command_failed"), receipt.get("_stderr", "")
