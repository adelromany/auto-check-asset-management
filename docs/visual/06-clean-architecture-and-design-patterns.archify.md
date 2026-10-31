# 06 — Clean Architecture & Design Patterns

Summary (generated from the headings): This page has 5 sections. It keeps every rule in the source file and adds no new rule.

## Layers at a glance {#layers-at-a-glance-panel}

@architecture id=layer-map title="Allowed dependency direction"
| router | routers | frontend |
| service | services | backend |
| data | repositories / clients | backend |
| store | db / external systems | database |
| domain | domain (pure) | backend |
| security | security (HTTP hardening) | security |
| router > service | calls |
| service > data | uses |
| data > store | reads / writes |
| service > domain | pure rules |
| router > security | guarded by |

## Layers and the dependency rule {#layers-and-the-dependency-rule-0}

```
routers → services → repositories / clients → db / external systems
              ↓
            domain (pure)

app/security/*  cross-cutting HTTP hardening, imported by main/pages only
```

| Rule | Text |
| --- | --- |
| ARC-01 {#arc-01} | `app/domain/*`: pure Python, standard library only. No I/O, no framework imports, no clock reads (time is passed in). |
| ARC-02 {#arc-02} | `app/repositories/*`: the main place reusable queries are written. They return model objects or small DTOs, never expose sessions to callers above services. **Recorded exception:** the read-only dashboard aggregates in `app/services/dashboard.py` build their SQLAlchemy `select`/`func` expressions directly on the injected session because they are a single read-only reporting use case; they never write and never leak the session. Moving them into a repository is a future refactor, not a hidden rule. |
| ARC-03 {#arc-03} | `app/clients/*`: the only place external HTTP is spoken. They translate external responses and errors into typed results and typed exceptions. |
| ARC-04 {#arc-04} | `app/services/*`: orchestration, idempotency, verification, transactions. No `fastapi` imports, no HTTP status codes (raise domain/service exceptions; routers map them). |
| ARC-05 {#arc-05} | `app/routers/*`: parse input, enforce authentication, call exactly one service operation, return a DTO. No business logic, no direct DB or `httpx`. |
| ARC-06 {#arc-06} | `app/dto/*`: pydantic request/response models. Database models are never returned directly. |
| ARC-07 {#arc-07} | `app/config.py` is the only reader of environment variables. |
| ARC-08 {#arc-08} | `tests/test_architecture_rules.py` enforces [ARC-01](block:arc-01), 04, 05 automatically. `tests/test_graph_consistency.py` keeps the module/route graph honest. Security middleware is tested separately in `tests/test_security_hardening.py`. |
| ARC-20 {#arc-20} | `app/security/*` is a cross-cutting infrastructure package: startup validation, CSRF/Origin, headers and the in-memory limiter. It may import `app/config.py`; routers and services must not depend on it for business behavior. |

## Patterns to use (and only where they earn their place) {#patterns-to-use-and-only-where-they-earn-their-place-1}

| Rule | Text |
| --- | --- |
| ARC-09 {#arc-09} | Repository: data access for handovers and events. |
| ARC-10 {#arc-10} | Adapter/Client: `SnipeItClient` hides Snipe-IT's wire format. |
| ARC-11 {#arc-11} | Strategy/Provider: `SnipeItCredentialProvider` so the token source can change later without touching services. |
| ARC-12 {#arc-12} | State machine via pure functions: stage ordering, `can_run`, `derive_status` live in the domain. |
| ARC-21 {#arc-21} | Hardware and software evidence evaluation lives in pure `app/domain/software_rules.py`; `app/services/software_check.py` coordinates the persisted override and reevaluation. |
| ARC-13 {#arc-13} | Dependency injection through FastAPI `Depends` and constructor arguments; tests override them. |
| ARC-14 {#arc-14} | Unit of work: one request, one database session, commit in a single place (`get_session`). |

## Patterns to avoid {#patterns-to-avoid-2}

| Rule | Text |
| --- | --- |
| ARC-15 {#arc-15} | No generic base repositories, no abstract factories, no event buses, no plugin systems, no premature configurability. Add abstraction only when a second concrete need exists. |

## Database sessions (async) {#database-sessions-async-3}

| Rule | Text |
| --- | --- |
| ARC-16 {#arc-16} | `expire_on_commit=False`. No lazy loading: load what you need explicitly (`selectinload`). No ORM objects used after the session closes. |
| ARC-17 {#arc-17} | The engine is created lazily; importing the app never opens a database connection (the characterization tests depend on this). |
| ARC-18 {#arc-18} | Schema changes only through Alembic migrations. No `create_all` in application code. |

## Compatibility {#compatibility-4}

| Rule | Text |
| --- | --- |
| ARC-19 {#arc-19} | Existing endpoints keep their paths and response shapes. New behavior is added through new endpoints or optional parameters whose default preserves current behavior. |

## Source {#source}

@facts
| Source Markdown | `docs/principles/06-clean-architecture-and-design-patterns.md` |
| SHA-256 | `6c06903db0959346f12f334412f6e450fd1fa1ca94466c37cc108abac6d5068d` |
| Repository link | [Open the Markdown source](https://github.com/adelromany/auto-check-asset-management/blob/main/docs/principles/06-clean-architecture-and-design-patterns.md) |
