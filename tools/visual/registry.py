"""The ordered list of committed visual artifacts.

Part 1 registered nothing.  Part 2 adds the twelve principle explainers and
the static index.  Later branches append the graph and handover artifacts.
"""

from __future__ import annotations

from .artifacts import Artifact
from .graph import (
    build_focus,
    build_graph_index,
    build_modules,
    build_overview,
    build_violations,
)
from .handover import (
    build_dependencies,
    build_differences,
    build_erd,
    build_handover_index,
    build_lifecycle,
    build_sequence,
    build_stage_lifecycle,
    build_workflow,
)
from .principles import PAGES, build_index, principle_source

ARTIFACTS: list[Artifact] = [
    *[
        Artifact(
            key=f"principle-{page.number}",
            source_name=f"{page.key}.archify.md",
            output_name=f"{page.key}.html",
            diagram_type="explainer",
            build=lambda page=page: principle_source(page),
        )
        for page in PAGES
    ],
    Artifact(
        key="graph-architecture",
        source_name="graph/architecture-overview.json",
        output_name="graph/architecture-overview.html",
        diagram_type="architecture",
        build=build_overview,
    ),
    Artifact(
        key="graph-modules",
        source_name="graph/architecture-modules.json",
        output_name="graph/architecture-modules.html",
        diagram_type="architecture",
        build=build_modules,
    ),
    *[
        Artifact(
            key=f"graph-focus-{layer}",
            source_name=f"graph/focus-{layer}.json",
            output_name=f"graph/focus-{layer}.html",
            diagram_type="architecture",
            build=lambda layer=layer: build_focus(layer),
        )
        for layer in ("router", "service", "repository", "client", "db", "dto", "domain", "config", "infra")
    ],
    Artifact(
        key="graph-violations",
        source_name="graph/violations.json",
        output_name="graph/violations.html",
        diagram_type="architecture",
        build=build_violations,
    ),
    Artifact(
        key="graph-index",
        source_name="",
        output_name="graph/index.html",
        diagram_type="static",
        build=build_graph_index,
        static=True,
    ),
    Artifact(
        key="handover-workflow",
        source_name="handover/workflow.json",
        output_name="handover/workflow.html",
        diagram_type="workflow",
        build=build_workflow,
    ),
    Artifact(
        key="handover-dependencies",
        source_name="handover/dependencies.json",
        output_name="handover/dependencies.html",
        diagram_type="workflow",
        build=build_dependencies,
    ),
    Artifact(
        key="handover-sequence",
        source_name="handover/sequence.json",
        output_name="handover/sequence.html",
        diagram_type="sequence",
        build=build_sequence,
    ),
    Artifact(
        key="handover-lifecycle",
        source_name="handover/lifecycle.json",
        output_name="handover/lifecycle.html",
        diagram_type="lifecycle",
        build=build_lifecycle,
    ),
    Artifact(
        key="handover-stage-lifecycle",
        source_name="handover/stage-lifecycle.json",
        output_name="handover/stage-lifecycle.html",
        diagram_type="lifecycle",
        build=build_stage_lifecycle,
    ),
    Artifact(
        key="handover-erd",
        source_name="handover/erd.json",
        output_name="handover/erd.html",
        diagram_type="erd",
        build=build_erd,
    ),
    Artifact(
        key="handover-differences",
        source_name="handover/differences.archify.md",
        output_name="handover/differences.html",
        diagram_type="explainer",
        build=build_differences,
    ),
    Artifact(
        key="handover-index",
        source_name="",
        output_name="handover/index.html",
        diagram_type="static",
        build=build_handover_index,
        static=True,
    ),
    Artifact(
        key="index",
        source_name="",
        output_name="index.html",
        diagram_type="static",
        build=build_index,
        static=True,
    ),
]
