# 03 — Graph Principles (rules + LIVE GRAPH)

The project graph is a map of what depends on what, so any change can be assessed for impact before it is made. It is part of the code: it is updated in the SAME branch as the change that alters it, and a test enforces consistency.

## Rules
- GRF-01 Node kinds: `module` (a Python file under `app/`), `route` (HTTP method + path), `table` (DB table), `external` (outside system), `stage` (handover stage), `asset` (templates / static JS).
- GRF-02 Edge kinds: `imports`, `calls`, `reads`, `writes`, `exposes` (module → route), `renders` (route → template), `depends_on` (stage → stage), `uses` (module → external).
- GRF-03 Allowed import direction: routers → services → repositories/clients → db/external; `domain` imports nothing from `app`. Any edge that violates this is a defect, not a graph entry.
- GRF-04 Every `.py` file under `app/` (except `__init__.py`) appears as a `module` node in the table below. Every `module` node listed exists on disk. `tests/test_graph_consistency.py` enforces both directions.
- GRF-05 Every new route is listed with its exposing module. Every table is listed with the modules that read and write it.
- GRF-06 The Impact table answers "if I change X, what must I re-check?". Update it whenever a node's responsibilities change.
- GRF-07 The Mermaid diagram is a human summary; the node and edge tables are the source of truth.
- GRF-08 Do not record speculative or planned nodes. The graph describes what exists in the repository now.
- GRF-09 When you finish a task, updating this section is part of the definition of done.

## Consistency test (specification for `tests/test_graph_consistency.py`)
1. Read this file; extract the text between `<!-- GRAPH:START -->` and `<!-- GRAPH:END -->`.
2. Parse rows of the node table whose first cell is `module`; the second cell is a repo-relative path.
3. Assert: every listed module path exists; every `app/**/*.py` except `__init__.py` is listed.
4. Assert: every module's declared layer (third cell: `router|service|repository|client|domain|db|config|infra|dto`) matches its directory (`app/routers` → router, `app/services` → service, `app/repositories` → repository, `app/clients` → client, `app/domain` → domain, `app/db` → db, `app/dto` → dto; others → config or infra).

## LIVE GRAPH
<!-- GRAPH:START -->
### Nodes — modules
| kind | path | layer | responsibility |
|---|---|---|---|
| module | app/main.py | infra | application factory, middleware and router wiring |
| module | app/config.py | config | the only place environment variables are read |
| module | app/dependencies.py | infra | current_user, session-store and Snipe-IT client injection, per-request DB session |
| module | app/auth.py | infra | Entra ID SSO routes (/login, /auth/callback, /logout) |
| module | app/schemas.py | dto | AgentPayload request model |
| module | app/db/base.py | db | declarative base and stable constraint naming |
| module | app/db/engine.py | db | lazy async engine and session factory (no connection at import) |
| module | app/db/models/handover.py | db | ORM models: Handover, HandoverStage, AgentReport, Document, Event |
| module | app/domain/stages.py | domain | nine fixed stages: keys, order, dependencies and statuses |
| module | app/domain/handover_rules.py | domain | pure derive_status, missing_steps and can_run rules |
| module | app/domain/errors.py | domain | typed handover workflow exceptions |
| module | app/domain/redaction.py | domain | strip windows_activation.partial_key before storage |
| module | app/clients/snipeit.py | client | Snipe-IT HTTP client, credential provider and typed results |
| module | app/dto/handover.py | dto | handover request/response models |
| module | app/repositories/handovers.py | repository | handover, stage and agent-report data access |
| module | app/repositories/events.py | repository | insert-only business event trail |
| module | app/services/handovers.py | service | create, get, list, confirm, cancel, recompute, agent report |
| module | app/services/snipeit_ops.py | service | recipient search/confirm, preview, checkin and verified checkout |
| module | app/services/sessions.py | service | in-memory short-code session store |
| module | app/routers/pages.py | router | index page and /api/me |
| module | app/routers/agent.py | router | session code create/poll/submit |
| module | app/routers/handovers.py | router | /api/handovers create, list, detail, confirm, cancel, recipient, preview, checkin, checkout |
| module | app/routers/snipeit.py | router | Snipe-IT device lookup and health |
| module | app/routers/health.py | router | liveness endpoint |
| module | app/routers/diag.py | router | clipboard diagnostics page (ENABLE_DIAG) |

### Nodes — routes
| kind | method path | exposed by |
|---|---|---|
| route | GET / | app/routers/pages.py |
| route | GET /api/me | app/routers/pages.py |
| route | GET /api/session/new | app/routers/agent.py |
| route | GET /api/session/{code}/data | app/routers/agent.py |
| route | POST /api/session/{code}/submit | app/routers/agent.py |
| route | POST /api/handovers | app/routers/handovers.py |
| route | GET /api/handovers | app/routers/handovers.py |
| route | GET /api/handovers/{id} | app/routers/handovers.py |
| route | POST /api/handovers/{id}/stages/{stage}/confirm | app/routers/handovers.py |
| route | POST /api/handovers/{id}/cancel | app/routers/handovers.py |
| route | POST /api/handovers/{id}/recipient/search | app/routers/handovers.py |
| route | POST /api/handovers/{id}/recipient/confirm | app/routers/handovers.py |
| route | GET /api/handovers/{id}/preview | app/routers/handovers.py |
| route | POST /api/handovers/{id}/checkin | app/routers/handovers.py |
| route | POST /api/handovers/{id}/checkout | app/routers/handovers.py |
| route | GET /api/snipeit/device | app/routers/snipeit.py |
| route | GET /api/snipeit/health | app/routers/snipeit.py |
| route | GET /api/health | app/routers/health.py |

### Nodes — external systems
| kind | name | used by |
|---|---|---|
| external | Snipe-IT API | app/clients/snipeit.py |
| external | Entra ID (OIDC) | app/auth.py |

### Nodes — tables
| kind | table | read by | written by |
|---|---|---|---|
| table | handovers | app/repositories/handovers.py | app/repositories/handovers.py |
| table | handover_stages | app/repositories/handovers.py | app/repositories/handovers.py |
| table | agent_reports | app/repositories/handovers.py | app/repositories/handovers.py |
| table | documents | — (repository arrives in Phase 6) | — |
| table | events | app/repositories/events.py | app/repositories/events.py |

### Edges (selected, source of truth for impact)
| from | edge | to |
|---|---|---|
| app/routers/agent.py | imports | app/services/sessions.py |
| app/routers/agent.py | imports | app/schemas.py |
| app/routers/snipeit.py | imports | app/clients/snipeit.py |
| app/clients/snipeit.py | uses | Snipe-IT API |
| app/auth.py | uses | Entra ID (OIDC) |
| app/main.py | imports | app/routers/* |
| app/dependencies.py | imports | app/db/engine.py |
| app/dependencies.py | imports | app/clients/snipeit.py |
| app/db/engine.py | reads | DATABASE_URL (app/config.py) |
| app/repositories/events.py | imports | app/db/models/handover.py |
| app/repositories/handovers.py | imports | app/db/models/handover.py |
| app/repositories/handovers.py | imports | app/domain/stages.py |
| app/services/handovers.py | imports | app/repositories/handovers.py |
| app/services/handovers.py | imports | app/repositories/events.py |
| app/services/handovers.py | uses | app/domain/handover_rules.py |
| app/services/handovers.py | imports | app/domain/redaction.py |
| app/services/snipeit_ops.py | imports | app/services/handovers.py |
| app/services/snipeit_ops.py | imports | app/clients/snipeit.py |
| app/services/snipeit_ops.py | imports | app/repositories/events.py |
| app/routers/handovers.py | imports | app/services/handovers.py |
| app/routers/handovers.py | imports | app/services/snipeit_ops.py |
| app/routers/handovers.py | imports | app/dto/handover.py |
| app/routers/agent.py | imports | app/services/handovers.py |
| alembic/env.py | imports | app/db/base.py |

### Impact table
| if you change | re-check |
|---|---|
| app/config.py | every module reading settings; tests/conftest.py BASE_ENV; .env.example |
| app/services/sessions.py | app/routers/agent.py; tests/test_characterization.py |
| app/schemas.py (AgentPayload) | static/agent.ps1, static/agent.sh, app/routers/agent.py, the report page |
| app/routers/snipeit.py response shape | static/app.js lookup rendering; tests/test_characterization.py |
| app/db/models/handover.py | alembic/versions/0001_initial.py; repositories; tests/test_persistence.py |
| app/db/engine.py | app/dependencies.py get_session; tests that override DATABASE_URL |
| app/domain/stages.py | app/domain/handover_rules.py; app/services/handovers.py; tests/test_domain_rules.py |
| app/services/handovers.py | app/routers/handovers.py; app/routers/agent.py; tests/test_handover_service.py; tests/test_handovers_api.py |
| app/services/snipeit_ops.py | app/routers/handovers.py; tests/test_snipeit_write_ops.py; tests/fakes/snipeit_fake.py |
| app/dependencies.py get_snipeit_client | app/routers/handovers.py; tests/test_snipeit_write_ops.py |
| app/clients/snipeit.py | app/routers/snipeit.py; app/services/snipeit_ops.py; tests/test_snipeit_client.py; tests/fakes/snipeit_fake.py |
| app/repositories/events.py | every service that writes an event; LOG-07 test |
<!-- GRAPH:END -->
