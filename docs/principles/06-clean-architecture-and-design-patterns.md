# 06 — Clean Architecture & Design Patterns

## Layers and the dependency rule
```
routers → services → repositories / clients → db / external systems
              ↓
            domain (pure)
```
- ARC-01 `app/domain/*`: pure Python, standard library only. No I/O, no framework imports, no clock reads (time is passed in).
- ARC-02 `app/repositories/*`: the only place queries are written. They return model objects or small DTOs, never expose sessions to callers above services.
- ARC-03 `app/clients/*`: the only place external HTTP is spoken. They translate external responses and errors into typed results and typed exceptions.
- ARC-04 `app/services/*`: orchestration, idempotency, verification, transactions. No `fastapi` imports, no HTTP status codes (raise domain/service exceptions; routers map them).
- ARC-05 `app/routers/*`: parse input, enforce authentication, call exactly one service operation, return a DTO. No business logic, no direct DB or `httpx`.
- ARC-06 `app/dto/*`: pydantic request/response models. Database models are never returned directly.
- ARC-07 `app/config.py` is the only reader of environment variables.
- ARC-08 `tests/test_architecture_rules.py` enforces ARC-01, 04, 05 automatically.

## Patterns to use (and only where they earn their place)
- ARC-09 Repository: data access for handovers and events.
- ARC-10 Adapter/Client: `SnipeItClient` hides Snipe-IT's wire format.
- ARC-11 Strategy/Provider: `SnipeItCredentialProvider` so the token source can change later without touching services.
- ARC-12 State machine via pure functions: stage ordering, `can_run`, `derive_status` live in the domain.
- ARC-13 Dependency injection through FastAPI `Depends` and constructor arguments; tests override them.
- ARC-14 Unit of work: one request, one database session, commit in a single place (`get_session`).

## Patterns to avoid
- ARC-15 No generic base repositories, no abstract factories, no event buses, no plugin systems, no premature configurability. Add abstraction only when a second concrete need exists.

## Database sessions (async)
- ARC-16 `expire_on_commit=False`. No lazy loading: load what you need explicitly (`selectinload`). No ORM objects used after the session closes.
- ARC-17 The engine is created lazily; importing the app never opens a database connection (the characterization tests depend on this).
- ARC-18 Schema changes only through Alembic migrations. No `create_all` in application code.

## Compatibility
- ARC-19 Existing endpoints keep their paths and response shapes. New behavior is added through new endpoints or optional parameters whose default preserves current behavior.
