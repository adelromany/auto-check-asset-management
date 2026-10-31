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
| module | app/security/startup.py | infra | fail-closed SESSION_SECRET check when SSO is on |
| module | app/security/csrf.py | infra | per-session CSRF token and Origin check for cookie-authenticated writes |
| module | app/security/headers.py | infra | self-only CSP and fixed security headers on every response |
| module | app/security/ratelimit.py | infra | in-memory limits for agent submit and recipient search |
| module | app/middleware/request_id.py | infra | server-generated request ID context and response header |
| module | app/request_context.py | infra | context variable for the current request ID |
| module | app/logging_config.py | infra | key-value UTC logging setup and request-ID filter |
| module | app/dependencies.py | infra | current_user, session-store and Snipe-IT client injection, per-request DB session |
| module | app/auth.py | infra | Entra ID SSO routes (/login, /auth/callback, /logout) |
| module | app/schemas.py | dto | AgentPayload request model |
| module | app/db/base.py | db | declarative base and stable constraint naming |
| module | app/db/engine.py | db | lazy async engine and session factory (no connection at import) |
| module | app/db/models/handover.py | db | ORM models: Handover, HandoverStage, AgentReport, Document, Event |
  | module | app/domain/stages.py | domain | ten fixed stages: keys, order, dependencies and statuses |
| module | app/domain/handover_rules.py | domain | pure derive_status, missing_steps and can_run rules |
  | module | app/domain/software_rules.py | domain | pure hardware, required software and activation evaluators |
| module | app/domain/errors.py | domain | typed handover workflow exceptions |
| module | app/domain/redaction.py | domain | strip windows_activation.partial_key before storage |
| module | app/domain/recipient_identity.py | domain | interactive domain-user detection and engineer match |
| module | app/domain/timeutil.py | domain | normalize persistence datetimes to UTC |
| module | app/clients/snipeit.py | client | Snipe-IT HTTP client, credential provider and typed results |
| module | app/dto/handover.py | dto | handover request/response models |
| module | app/dto/dashboard.py | dto | dashboard summary and paged-row response models |
| module | app/repositories/handovers.py | repository | handover, stage and agent-report data access |
| module | app/repositories/documents.py | repository | stored evidence document data access |
| module | app/repositories/events.py | repository | insert-only business event trail |
| module | app/services/handovers.py | service | create, get, list, confirm, cancel, recompute, agent report |
| module | app/services/software_check.py | service | override and re-evaluation of software checks |
| module | app/services/snipeit_ops.py | service | recipient search/confirm, preview, checkin and verified checkout |
| module | app/services/documents.py | service | printable report, safe scan storage, download and verified push |
| module | app/services/dashboard.py | service | database-side dashboard aggregates and page-sized handover rows |
| module | app/services/sessions.py | service | in-memory short-code session store |
| module | app/routers/pages.py | router | index, handover dashboard and case pages, /api/me |
| module | app/routers/agent.py | router | session code create/poll/submit |
| module | app/routers/handovers.py | router | /api/handovers create, list, detail, confirm, cancel, recipient, preview, checkin, checkout |
| module | app/routers/documents.py | router | report page, document upload/download and push |
| module | app/routers/dashboard.py | router | /api/dashboard summary and paged-row reads |
| module | app/routers/http_errors.py | router | shared domain/client error to HTTP mapping and detail DTO |
| module | app/routers/snipeit.py | router | Snipe-IT device lookup and health |
| module | app/routers/health.py | router | liveness endpoint |
| module | app/routers/diag.py | router | clipboard diagnostics page (ENABLE_DIAG) |
| module | tools/build_principles_visual.py | infra | deterministic offline principle visual generator |
| module | tools/graph_data.py | infra | shared LIVE GRAPH parsing for generation and consistency tests |
| module | tools/build_handover_workflow.py | infra | generates code-derived handover workflow visual |

### Nodes — routes
| kind | method path | exposed by |
|---|---|---|
| route | GET / | app/routers/pages.py |
| route | GET /handovers | app/routers/pages.py |
| route | GET /handovers/{id} | app/routers/pages.py |
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
| route | POST /api/handovers/{id}/software-check/override | app/routers/handovers.py |
| route | POST /api/handovers/{id}/software-check/reevaluate | app/routers/handovers.py |
| route | POST /api/handovers/{id}/recipient/confirm | app/routers/handovers.py |
| route | GET /api/handovers/{id}/preview | app/routers/handovers.py |
| route | POST /api/handovers/{id}/checkin | app/routers/handovers.py |
| route | POST /api/handovers/{id}/checkout | app/routers/handovers.py |
| route | GET /api/handovers/{id}/report | app/routers/documents.py |
| route | POST /api/handovers/{id}/document | app/routers/documents.py |
| route | GET /api/handovers/{id}/document | app/routers/documents.py |
| route | POST /api/handovers/{id}/document/push | app/routers/documents.py |
| route | GET /api/dashboard/handovers/summary | app/routers/dashboard.py |
| route | GET /api/dashboard/handovers | app/routers/dashboard.py |
| route | GET /api/snipeit/device | app/routers/snipeit.py |
| route | GET /api/snipeit/health | app/routers/snipeit.py |
| route | GET /api/health | app/routers/health.py |

### Nodes — external systems
| kind | name | used by |
|---|---|---|
| external | Snipe-IT API | app/clients/snipeit.py |
| external | Entra ID (OIDC) | app/auth.py |

### Nodes — stages (fixed order)
| kind | stage | depends on |
|---|---|---|
| stage | device_prepared | — |
| stage | user_signed_in | device_prepared |
| stage | agent_report | device_prepared |
| stage | software_check | agent_report |
| stage | recipient_check | agent_report |
| stage | checkout | recipient_check; software_check |
| stage | report_printed | agent_report |
| stage | user_signed | report_printed |
| stage | document_scanned | user_signed |
| stage | document_pushed | document_scanned |

### Nodes — tables
| kind | table | read by | written by |
|---|---|---|---|
| table | handovers | app/repositories/handovers.py; app/services/dashboard.py | app/repositories/handovers.py |
| table | handover_stages | app/repositories/handovers.py; app/services/dashboard.py | app/repositories/handovers.py |
| table | agent_reports | app/repositories/handovers.py | app/repositories/handovers.py |
| table | documents | app/repositories/documents.py | app/repositories/documents.py |
| table | events | app/repositories/events.py | app/repositories/events.py |

### Nodes — assets (templates / static JS)
| kind | path | used by | purpose |
|---|---|---|---|
| asset | templates/index.html | GET / | landing page and "Start handover" entry link |
| asset | templates/diag_clipboard.html | GET /diag/clipboard | clipboard diagnostics page |
| asset | templates/handover_report.html | GET /api/handovers/{id}/report | printable report |
| asset | static/css/report.css | handover_report.html | printable report styles, external for CSP |
| asset | templates/handovers.html | GET /handovers | server-rendered dashboard shell |
| asset | templates/handover_detail.html | GET /handovers/{id} | server-rendered case page |
| asset | templates/partials/page_head.html | handovers.html, handover_detail.html | shared head, CSS and theme bootstrap |
| asset | templates/partials/topbar.html | handovers.html, handover_detail.html | shared navigation and SSO identity |
| asset | templates/partials/labels.html | handovers.html, handover_detail.html | escaping macros for status/stage labels |
| asset | static/js/shell.js | handovers.html, handover_detail.html | shared topbar/theme/toast helpers |
| asset | static/js/handovers.js | handovers.html | filters, KPI refresh and table states via textContent |
| asset | static/js/handover_detail.js | handover_detail.html | stage actions, recipient, preview, upload and push |
| asset | static/js/diag_clipboard.js | diag_clipboard.html | clipboard diagnostics, external for CSP |
| asset | static/js/theme-init.js | page_head.html, index.html, diag_clipboard.html | pre-paint theme, external for CSP |
| asset | static/js/theme.js | index.html, handovers.html, handover_detail.html, diag_clipboard.html | theme toggle |
| asset | static/js/clipboard.js | index.html | shared copyText utility |
| asset | static/app.js | index.html | legacy landing-page UI |

### Edges (selected, source of truth for impact)
| from | edge | to |
|---|---|---|
| app/routers/agent.py | imports | app/services/sessions.py |
| app/routers/agent.py | imports | app/schemas.py |
| app/routers/snipeit.py | imports | app/clients/snipeit.py |
| app/clients/snipeit.py | uses | Snipe-IT API |
| app/auth.py | uses | Entra ID (OIDC) |
| stage user_signed_in | depends_on | stage device_prepared |
| stage agent_report | depends_on | stage device_prepared |
| stage recipient_check | depends_on | stage agent_report |
| stage checkout | depends_on | stage recipient_check |
| stage report_printed | depends_on | stage agent_report |
| stage user_signed | depends_on | stage report_printed |
| stage document_scanned | depends_on | stage user_signed |
| stage document_pushed | depends_on | stage document_scanned |
| app/main.py | imports | app/routers/* |
| app/main.py | imports | app/security/startup.py |
| app/main.py | imports | app/security/csrf.py |
| app/main.py | imports | app/security/headers.py |
| app/main.py | imports | app/security/ratelimit.py |
| app/main.py | imports | app/middleware/request_id.py |
| app/main.py | imports | app/logging_config.py |
| app/middleware/request_id.py | imports | app/request_context.py |
| app/logging_config.py | imports | app/request_context.py |
| app/logging_config.py | imports | app/config.py |
| app/routers/pages.py | imports | app/security/csrf.py |
| app/security/startup.py | imports | app/config.py |
| app/security/csrf.py | imports | app/config.py |
| app/security/ratelimit.py | imports | app/config.py |
| app/dependencies.py | imports | app/db/engine.py |
| app/dependencies.py | imports | app/clients/snipeit.py |
| app/db/engine.py | reads | DATABASE_URL (app/config.py) |
| app/repositories/documents.py | imports | app/db/models/handover.py |
| app/repositories/events.py | imports | app/db/models/handover.py |
| app/repositories/handovers.py | imports | app/db/models/handover.py |
| app/repositories/handovers.py | imports | app/domain/stages.py |
| app/services/handovers.py | imports | app/repositories/handovers.py |
| app/services/handovers.py | imports | app/repositories/events.py |
| app/services/handovers.py | uses | app/domain/handover_rules.py |
| app/services/handovers.py | uses | app/domain/software_rules.py |
| app/services/handovers.py | uses | app/domain/recipient_identity.py |
| app/services/handovers.py | uses | app/domain/timeutil.py |
| app/services/handovers.py | imports | app/domain/redaction.py |
| app/services/snipeit_ops.py | imports | app/services/handovers.py |
| app/services/snipeit_ops.py | uses | app/domain/recipient_identity.py |
| app/services/snipeit_ops.py | imports | app/clients/snipeit.py |
| app/services/snipeit_ops.py | imports | app/repositories/events.py |
| app/services/documents.py | imports | app/repositories/documents.py |
| app/services/documents.py | imports | app/repositories/events.py |
| app/services/documents.py | imports | app/services/handovers.py |
| app/services/documents.py | imports | app/services/snipeit_ops.py |
| app/services/documents.py | imports | app/clients/snipeit.py |
| app/routers/handovers.py | imports | app/services/handovers.py |
| app/routers/handovers.py | imports | app/services/software_check.py |
| app/routers/handovers.py | imports | app/services/snipeit_ops.py |
| app/routers/handovers.py | imports | app/dto/handover.py |
| app/routers/handovers.py | imports | app/routers/http_errors.py |
| app/routers/documents.py | imports | app/services/documents.py |
| app/routers/documents.py | imports | app/routers/http_errors.py |
| app/routers/dashboard.py | imports | app/services/dashboard.py |
| app/routers/dashboard.py | imports | app/dto/dashboard.py |
| app/services/dashboard.py | imports | app/services/handovers.py |
| app/services/dashboard.py | imports | app/dto/dashboard.py |
| app/services/dashboard.py | imports | app/dto/handover.py |
| app/services/dashboard.py | reads | handovers table |
| app/services/dashboard.py | reads | handover_stages table |
| app/services/dashboard.py | uses | app/domain/timeutil.py |
| app/routers/pages.py | uses | app/domain/recipient_identity.py |
| app/routers/pages.py | uses | app/domain/handover_rules.py |
| app/routers/pages.py | imports | app/services/dashboard.py |
| app/routers/pages.py | imports | app/services/handovers.py |
| app/routers/pages.py | renders | templates/handovers.html |
| app/routers/pages.py | renders | templates/handover_detail.html |
| templates/handovers.html | uses | static/js/handovers.js |
| templates/handover_detail.html | uses | static/js/handover_detail.js |
| app/routers/http_errors.py | imports | app/services/handovers.py |
| app/routers/http_errors.py | imports | app/clients/snipeit.py |
| app/routers/http_errors.py | imports | app/domain/errors.py |
| app/routers/agent.py | imports | app/services/handovers.py |
| tools/build_principles_visual.py | imports | tools/graph_data.py |
| alembic/env.py | imports | app/db/base.py |

### Impact table
| if you change | re-check |
|---|---|
| app/config.py | every module reading settings; tests/conftest.py BASE_ENV; .env.example |
| app/middleware/request_id.py | app/main.py outer middleware order; app/logging_config.py; request-ID tests |
| app/logging_config.py | app/main.py startup; app/clients/snipeit.py; logging tests |
| app/domain/recipient_identity.py | app/services/handovers.py; app/services/snipeit_ops.py; app/routers/pages.py; static/agent.ps1 |
| app/domain/timeutil.py | age rules; dashboard SQL comparisons; SQLite datetime tests |
| app/services/software_check.py | app/routers/handovers.py; static/js/software_check.js; migration and override tests |
| app/security/startup.py | app/main.py create_app; tests/test_security_hardening.py; deployment .env |
| app/security/csrf.py | app/main.py; app/routers/pages.py /api/me; static/js/shell.js; every protected POST test |
| app/security/headers.py | app/main.py; every template (no inline script/style or external host); tests/test_security_hardening.py |
| app/security/ratelimit.py | app/main.py; agent submit and recipient search tests; deployment worker model |
| app/services/sessions.py | app/routers/agent.py; tests/test_characterization.py |
| app/schemas.py (AgentPayload) | static/agent.ps1, static/agent.sh, app/routers/agent.py, the report page |
| app/routers/snipeit.py response shape | static/app.js lookup rendering; tests/test_characterization.py |
| app/db/models/handover.py | alembic/versions/0001_initial.py; repositories; tests/test_persistence.py |
| app/db/engine.py | app/dependencies.py get_session; tests that override DATABASE_URL |
| app/domain/stages.py | app/domain/handover_rules.py; app/services/handovers.py; tests/test_domain_rules.py |
| app/services/handovers.py | app/routers/handovers.py; app/routers/agent.py; tests/test_handover_service.py; tests/test_handovers_api.py |
| app/services/snipeit_ops.py | app/routers/handovers.py; tests/test_snipeit_write_ops.py; tests/fakes/snipeit_fake.py |
| app/services/documents.py | app/routers/documents.py; templates/handover_report.html; tests/test_documents.py |
| app/repositories/documents.py | app/services/documents.py; documents table |
| app/routers/http_errors.py | app/routers/handovers.py; app/routers/documents.py; every error-status test |
| app/dependencies.py get_snipeit_client | app/routers/handovers.py; tests/test_snipeit_write_ops.py |
| app/clients/snipeit.py | app/routers/snipeit.py; app/services/snipeit_ops.py; tests/test_snipeit_client.py; tests/fakes/snipeit_fake.py |
| app/repositories/events.py | every service that writes an event; LOG-07 test |
| app/services/dashboard.py | app/routers/dashboard.py; app/routers/pages.py; templates/handovers.html; static/js/handovers.js; tests/test_dashboard.py |
| app/dto/dashboard.py | app/services/dashboard.py; app/routers/dashboard.py; static/js/handovers.js |
| app/routers/dashboard.py | static/js/handovers.js; tests/test_dashboard.py; every dashboard date-filter test |
| templates/partials/labels.html | templates/handovers.html; templates/handover_detail.html; escaping test |
| static/js/shell.js | templates/partials/topbar.html; both handover pages; toast rendering |
| static/js/handover_detail.js | templates/handover_detail.html; every stage/recipient/document action test |
<!-- GRAPH:END -->
