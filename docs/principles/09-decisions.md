# 09 — Decisions

Format per entry: ID, date, status (AGREED / PROPOSED / OPEN / IMPLEMENTED), context, decision, consequences. New decisions are appended; superseded ones are marked, never deleted.

## Agreed by the owner (before this engagement)
- D-01 AGREED — Independent portal integrated with Lab Care; a human decides which tickets are handovers.
- D-02 AGREED — Two identities: engineer (SSO) and recipient (detected on the device, confirmed by the engineer).
- D-03 AGREED — Snipe-IT writes should be attributed to the engineer; mechanism undecided (see D-12).
- D-04 AGREED — Database: PostgreSQL target (SQLite acceptable for development and tests).
- D-05 AGREED — Terminology follows Snipe-IT: checkout / checkin.
- D-06 AGREED — Paper signature stays; e-signature rejected by legal.
- D-07 AGREED — Git: never commit to `feature/sso` or `main`; one concern per branch.
- D-08 AGREED — Two dashboards eventually; this engagement delivers dashboard 1 (handovers).

## Decisions made in this engagement
- D-09 IMPLEMENTED — SQLAlchemy 2 async + Alembic; `DATABASE_URL` selects PostgreSQL (asyncpg) or SQLite (aiosqlite). Consequence: models restricted to portable types.
- D-10 IMPLEMENTED — Nine fixed stages derived from the owner's flow diagram; status derived by pure functions; stored status recomputed in one place.
- D-11 AGREED — The signed sheet is stored by the portal and pushed to the device's Snipe-IT asset (stage 9 depends only on stage 8). A missing recipient blocks stages 4 and 5 and makes the handover stalled, but never blocks the document.
- D-12 OPEN — Attribution mechanism for Snipe-IT writes. Interim: service-account token behind `SnipeItCredentialProvider`; engineer email written into the Snipe-IT note and the events table. Limitation: Snipe-IT history may show the service account as actor. Requires a test: personal token → checkout → read asset history.
- D-13 AGREED — Document attach target is the device (asset), not the user. The exact endpoints are verified against the real Snipe-IT version in `docs/snipeit-api-verified.md`.
- D-14 OPEN — Stalled threshold by time, retention of events and documents, HTTPS rollout, agent single-use token binding.
- D-15 AGREED — H-Caliper is the owner's name for these 12 principle files; following H-Caliper means obeying and maintaining them.
- D-16 IMPLEMENTED — Graph file (`03-graph-principles.md`) is machine-checked by a test and updated in every branch that changes structure.
