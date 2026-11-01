#!/usr/bin/env python3
"""Build and check the committed Archify visual documentation.

Commands::

    python tools/visual/build_visuals.py build
    python tools/visual/build_visuals.py check
    python tools/visual/build_visuals.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.visual import archify
from tools.visual.artifacts import (
    MANIFEST_PATH,
    REPO_ROOT,
    VISUAL_ROOT,
    Artifact,
    manifest_bytes,
    sha256_bytes,
)
from tools.visual.registry import ARTIFACTS


def _selected(keys: list[str] | None) -> list[Artifact]:
    if not keys:
        return list(ARTIFACTS)
    wanted = tuple(keys)
    chosen = [
        item
        for item in ARTIFACTS
        if item.key in wanted or item.key.startswith(wanted)
    ]
    missing = [key for key in keys if not any(item.key.startswith(key) for item in chosen)]
    if missing:
        raise SystemExit(f"unknown artifact key(s): {', '.join(missing)}")
    return chosen


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.read_bytes() == data:
        return
    path.write_bytes(data)


def _receipt_dir(artifact: Artifact) -> Path:
    return VISUAL_ROOT / ".receipts" / artifact.key


def _print_receipt(artifact: Artifact, receipt: dict) -> None:
    status = receipt.get("status") or receipt.get("ok")
    gates = receipt.get("gates")
    if isinstance(gates, dict):
        gate_text = ", ".join(f"{name}={value}" for name, value in gates.items())
    else:
        gate_text = ""
    print(f"  {artifact.output_name}: status={status} {gate_text}".rstrip())
    summary = receipt.get("summary")
    if isinstance(summary, dict):
        for key in ("errors", "warnings", "checks"):
            if key in summary:
                print(f"    {key}: {summary[key]}")


def build(keys: list[str] | None, *, quality: str = "showcase", render: bool = True) -> int:
    artifacts = _selected(keys)
    if not artifacts:
        print("No visual artifacts are registered.")
        return 0
    if render and not archify.available():
        print(
            "Archify is not fetched. Run scripts/fetch_archify.sh first.",
            file=sys.stderr,
        )
        return 2

    for artifact in artifacts:
        source_text = artifact.source_text()
        if artifact.static:
            print(f"[static] {artifact.output_name}")
            _write(artifact.output_path, source_text.encode("utf-8"))
            continue

        assert artifact.source_path is not None
        _write(artifact.source_path, source_text.encode("utf-8"))
        print(f"[source] {artifact.source_name}")
        if not render:
            continue

        receipt = archify.finalize(
            artifact.diagram_type,
            VISUAL_ROOT.relative_to(REPO_ROOT) / artifact.source_name,
            VISUAL_ROOT.relative_to(REPO_ROOT) / artifact.output_name,
            quality=quality,
            writing="off",
            out_dir=Path(".receipts") / artifact.key,
        )
        _print_receipt(artifact, receipt)
        problems = archify.problems(receipt)
        if problems or receipt.get("_command_failed"):
            for problem in problems:
                print(f"    {problem}", file=sys.stderr)
            return 1
        if not artifact.output_path.is_file():
            print(
                f"    error: finalize reported success but {artifact.output_name} "
                "does not exist",
                file=sys.stderr,
            )
            return 1

    # The manifest always describes the whole committed set, even when the
    # command builds a subset with --only.
    _write(MANIFEST_PATH, manifest_bytes(ARTIFACTS))
    print(f"[manifest] {MANIFEST_PATH.relative_to(VISUAL_ROOT.parent.parent)}")
    return 0


def _all_committed_html() -> set[str]:
    return {
        path.relative_to(VISUAL_ROOT).as_posix()
        for path in VISUAL_ROOT.rglob("*.html")
        if ".receipts" not in path.parts
    }


def check(keys: list[str] | None, *, quality: str = "showcase") -> int:
    artifacts = _selected(keys)
    failures: list[str] = []

    if not artifacts:
        print("No visual artifacts are registered.")
        return 0
    if not archify.available():
        print(
            "Archify is not fetched. Run scripts/fetch_archify.sh first.",
            file=sys.stderr,
        )
        return 2

    for artifact in artifacts:
        source_text = artifact.source_text()
        if artifact.static:
            if not artifact.output_path.is_file():
                failures.append(f"{artifact.output_name}: missing")
            elif artifact.output_path.read_text(encoding="utf-8") != source_text:
                failures.append(f"{artifact.output_name}: differs from its builder")
            continue

        assert artifact.source_path is not None
        if not artifact.source_path.is_file():
            failures.append(f"{artifact.source_name}: missing")
            continue
        committed_source = artifact.source_path.read_text(encoding="utf-8")
        if committed_source != source_text:
            failures.append(
                f"{artifact.source_name}: differs from its builder "
                "(run build and commit the regenerated source)"
            )
            continue

        receipt = archify.validate(
            artifact.diagram_type,
            VISUAL_ROOT.relative_to(REPO_ROOT) / artifact.source_name,
            quality=quality,
            writing="off",
        )
        problems = archify.problems(receipt)
        if problems:
            failures.extend(
                f"{artifact.source_name}: {problem}" for problem in problems
            )
        elif receipt.get("_command_failed"):
            failures.append(
                f"{artifact.source_name}: validate failed: "
                f"{receipt.get('_stderr', '').strip()}"
            )

        if not artifact.output_path.is_file():
            failures.append(f"{artifact.output_name}: missing (run build)")
            continue
        print(f"[ok] {artifact.output_name}")

    # Every committed HTML must belong to a registered artifact.
    registered = {item.output_name for item in ARTIFACTS}
    extra = sorted(_all_committed_html() - registered)
    for name in extra:
        failures.append(f"{name}: committed HTML has no registered builder")

    if MANIFEST_PATH.is_file():
        committed = MANIFEST_PATH.read_bytes()
        expected = manifest_bytes(ARTIFACTS)
        if committed != expected:
            failures.append(
                "docs/visual/visual-manifest.json: differs from the builders "
                "(run build and commit the manifest)"
            )
    else:
        failures.append("docs/visual/visual-manifest.json: missing (run build)")

    # When delivery receipts exist, verify their source and artifact hashes.
    for artifact in artifacts:
        if artifact.static:
            continue
        receipt_path = artifact.output_path.with_suffix(".delivery.json")
        if not receipt_path.is_file():
            continue
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            failures.append(f"{receipt_path.name}: unreadable ({exc})")
            continue
        spec = receipt.get("specification", {}) if isinstance(receipt, dict) else {}
        art = receipt.get("artifact", {}) if isinstance(receipt, dict) else {}
        source_hash = spec.get("sha256") if isinstance(spec, dict) else None
        artifact_hash = art.get("sha256") if isinstance(art, dict) else None
        if source_hash and artifact.source_sha256() != source_hash:
            failures.append(
                f"{receipt_path.name}: source hash does not match the builder"
            )
        if artifact_hash and artifact.output_path.is_file():
            if sha256_bytes(artifact.output_path.read_bytes()) != artifact_hash:
                failures.append(
                    f"{receipt_path.name}: artifact hash does not match {artifact.output_name}"
                )

    if failures:
        print("\nVisual check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"\nVisual check passed for {len(artifacts)} artifact(s).")
    return 0


def list_artifacts() -> int:
    for artifact in ARTIFACTS:
        print(f"{artifact.key:40} {artifact.diagram_type:12} {artifact.output_name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "check", "list"])
    parser.add_argument("--only", nargs="+", metavar="KEY")
    parser.add_argument("--quality", default="showcase", choices=["standard", "showcase"])
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="for build: write sources only, without calling Archify",
    )
    args = parser.parse_args(argv)

    if args.command == "list":
        return list_artifacts()
    if args.command == "build":
        return build(args.only, quality=args.quality, render=not args.no_render)
    return check(args.only, quality=args.quality)


if __name__ == "__main__":
    raise SystemExit(main())
