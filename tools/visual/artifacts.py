"""Artifact descriptions, deterministic serialization, and the manifest."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
VISUAL_ROOT = REPO_ROOT / "docs" / "visual"
MANIFEST_PATH = VISUAL_ROOT / "visual-manifest.json"
MANIFEST_SCHEMA_VERSION = 1


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


@dataclass(frozen=True)
class Artifact:
    """One committed source/HTML pair.

    ``build`` returns either a JSON-serialisable mapping (native Archify
    diagrams) or the complete source text (explainer drafts and static pages).
    Static pages have no separate source file.
    """

    key: str
    source_name: str
    output_name: str
    diagram_type: str
    build: Callable[[], object]
    static: bool = False

    @property
    def source_path(self) -> Path | None:
        if self.static:
            return None
        return VISUAL_ROOT / self.source_name

    @property
    def output_path(self) -> Path:
        return VISUAL_ROOT / self.output_name

    def source_text(self) -> str:
        value = self.build()
        if isinstance(value, str):
            text = value
        elif isinstance(value, dict):
            text = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)
        else:
            raise TypeError(
                f"{self.key}: builder returned {type(value).__name__}, "
                "expected str or dict"
            )
        return text if text.endswith("\n") else text + "\n"

    def output_text(self) -> str:
        return self.source_text()

    def source_sha256(self) -> str | None:
        if self.static:
            return None
        return sha256_text(self.source_text())

    def output_sha256(self) -> str:
        return sha256_text(self.output_text())


def manifest_bytes(artifacts: list[Artifact]) -> bytes:
    entries = []
    for artifact in sorted(artifacts, key=lambda item: item.output_name):
        entries.append(
            {
                "key": artifact.key,
                "type": artifact.diagram_type,
                "source": artifact.source_name if not artifact.static else None,
                "source_sha256": artifact.source_sha256(),
                "html": artifact.output_name,
                "html_sha256": artifact.output_sha256(),
            }
        )
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generator": {
            "name": "Archify",
            "version": "3.2.0",
            "commit": "a4065941f12be7967436261d9934784e381d423c",
        },
        "artifacts": entries,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
