# Open Questions

Questions the implementation prompt does not answer, with the conservative
option taken in the meantime and who must decide. New entries are appended;
resolved entries are marked RESOLVED, never deleted.

Format: `## Q-<n> — <short title> (OPEN|RESOLVED)`, then context, conservative
option, and owner.

_No open questions yet._

## Q-1 — Does linking an agent session to a handover require ownership? (OPEN)

Context: `GET /api/session/new` accepts an optional `handover_id`, and the
unauthenticated agent later posts to `/api/session/{code}/submit`. The prompt
does not say whether the portal must verify that the handover exists and belongs
to the engineer who created the session code.

Conservative option taken: store the supplied id and let `/submit` ignore an
unknown, cancelled or completed handover; do not add a database lookup to
session creation. The session code is short-lived and random, and the engineer
chooses the id in the authenticated UI. If the owner wants stronger binding,
Phase 8 should validate existence and `engineer_email` at `/api/session/new`.

Owner: security owner.

## Q-2 — What does the `engineer` list filter match? (OPEN)

Context: `GET /api/handovers?engineer=` is specified as a filter but not as an
exact email, a name, or a substring search.

Conservative option taken: exact match on `engineer_email` (the identity the
portal records). A name/substring search can be added when the dashboard UI
defines its search box.

Owner: dashboard/UI owner.
