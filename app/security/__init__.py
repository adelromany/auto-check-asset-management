"""Cross-cutting security helpers (Phase 8).

Small, dependency-free pieces: startup validation, CSRF/origin protection,
security headers and an in-memory rate limiter. They live outside the
business layers so routers and services stay unaware of HTTP hardening.
"""
