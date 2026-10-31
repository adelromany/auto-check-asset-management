# 03 — Graph Principles (rules + LIVE GRAPH)

The project graph is a map of what depends on what, so any change can be assessed for impact before it is made. It is part of the code: it is updated in the SAME branch as the change that alters it, and a test enforces consistency.

## Rules {#rules-0}

| Rule | Text |
| --- | --- |
| GRF-01 {#grf-01} | Node kinds: `module` (a Python file under `app/`), `route` (HTTP method + path), `table` (DB table), `external` (outside system), `stage` (handover stage), `asset` (templates / static JS). |
| GRF-02 {#grf-02} | Edge kinds: `imports`, `calls`, `reads`, `writes`, `exposes` (module → route), `renders` (route → template), `depends_on` (stage → stage), `uses` (module → external). |
| GRF-03 {#grf-03} | Allowed import direction: routers → services → repositories/clients → db/external; `domain` imports nothing from `app`. Any edge that violates this is a defect, not a graph entry. |
| GRF-04 {#grf-04} | Every `.py` file under `app/` (except `__init__.py`) appears as a `module` node in the table below. Every `module` node listed exists on disk. `tests/test_graph_consistency.py` enforces both directions. |
| GRF-05 {#grf-05} | Every new route is listed with its exposing module. Every table is listed with the modules that read and write it. |
| GRF-06 {#grf-06} | The Impact table answers "if I change X, what must I re-check?". Update it whenever a node's responsibilities change. |
| GRF-07 {#grf-07} | The Mermaid diagram is a human summary; the node and edge tables are the source of truth. |
| GRF-08 {#grf-08} | Do not record speculative or planned nodes. The graph describes what exists in the repository now. |
| GRF-09 {#grf-09} | When you finish a task, updating this section is part of the definition of done. |

## Consistency test (specification for `tests/test_graph_consistency.py`) {#consistency-test-specification-for-tests-test-graph-consiste-1}

1. Read this file; extract the text between `<!-- GRAPH:START -->` and `<!-- GRAPH:END -->`.
2. Parse rows of the node table whose first cell is `module`; the second cell is a repo-relative path.
3. Assert: every listed module path exists; every `app/**/*.py` except `__init__.py` is listed.
4. Assert: every module's declared layer (third cell: `router|service|repository|client|domain|db|config|infra|dto`) matches its directory (`app/routers` → router, `app/services` → service, `app/repositories` → repository, `app/clients` → client, `app/domain` → domain, `app/db` → db, `app/dto` → dto; others → config or infra).
## LIVE GRAPH {#live-graph}

The node and edge tables in the Markdown file are the machine-checked source of truth. The diagrams below are generated from that section.

@facts
| Module nodes | 0 |
| Import edges | 0 |
| Route nodes | 0 |
| Table nodes | 0 |
| Stage nodes | 0 |
| Architecture overview | `docs/visual/graph/architecture-overview.html` |
| Every module | `docs/visual/graph/architecture-modules.html` |
| Layer focus views | `docs/visual/graph/focus-router.html` and four more |
| Violations | `docs/visual/graph/violations.html` |
| Freshness | `docs/visual/graph/index.html` |

@callout id=offline-diagrams level=note title="Open the diagram files beside this page"
The graph diagrams are standalone HTML files in `docs/visual/graph/`. The wrapper page adds the freshness banner and links every view.

## Source {#source}

@facts
| Source Markdown | `docs/principles/03-graph-principles.md` |
| SHA-256 | `2ef0fb1b2fa26e343b48e6fa64d1be540465a6706b6222f285c2d85328e6cb7c` |
| Repository link | [Open the Markdown source](https://github.com/adelromany/auto-check-asset-management/blob/main/docs/principles/03-graph-principles.md) |
