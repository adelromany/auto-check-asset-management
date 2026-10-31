# End-to-end verification (2026-10-31)

Run against the local portal at `http://127.0.0.1:8080` with
`SSO_ENABLED=false` and the development Snipe-IT v8.8.3 instance at
`http://localhost:8081`. The run used only asset `TEST-SN-0001`, user
`TEST-recipient` (Snipe-IT id 4), and a scan named
`TEST-e2e-signed.pdf`.

| Stage/action | Expected | Observed | Result |
|---|---|---|---|
| Create handover | New draft for TEST serial | HTTP 201; draft created | PASS |
| Device prepared | Explicit confirmation accepted | HTTP 200; in_progress | PASS |
| User signed in | Explicit confirmation accepted | HTTP 200; in_progress | PASS |
| Agent report + software check | Matching serial/hardware, all four configured ids installed, activation code 1 | HTTP 200; `agent_report` and `software_check` passed; only later stages remained missing | PASS |
| Recipient check | Engineer confirms the TEST Snipe-IT user | HTTP 200; recipient id 4 recorded | PASS |
| Preview | Return a dry-run without writes | HTTP 200; preview rendered before checkout | PASS |
| Checkout | Asset assigned to the confirmed recipient and verified by re-read | HTTP 200; final Snipe-IT API read showed asset assigned to user id 4 | PASS |
| Printed report | Printable HTML contains evidence and legal placeholder | HTTP 200; `[Company legal text goes here]` present | PASS |
| User signed | Explicit confirmation accepted | HTTP 200; in_progress | PASS |
| Scan upload | Accept PDF and mark `document_scanned` | HTTP 200; document record created | PASS |
| Push scan | Attach scan to the Snipe-IT asset and verify listing | HTTP 200; `document_pushed=passed`; Snipe-IT listing had one filename ending in `test-e2e-signed.pdf` | PASS |
| Dashboard | Summary reflects final handover status | HTTP 200; counts showed `completed=1`, all other statuses 0 | PASS |

Filename verification follows owner decision D-61: the Snipe-IT listing
rewrites names and exposes no file size, so only the normalized basename
suffix was compared. The portal's stored scan and Snipe-IT attachment were
not removed after the run.
