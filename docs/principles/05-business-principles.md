# 05 — Business Principles

## Vocabulary (use exactly these words in code, API, DB, UI)
- BIZ-01 **Handover**: one case of giving one device to one employee. **Checkout**: assign an asset to a user in Snipe-IT. **Checkin**: return an asset from a user in Snipe-IT. **Recipient**: the employee receiving the device. **Engineer**: the IT person performing the handover (SSO identity). **Stage**: one verifiable step of a handover.

## Principles
- BIZ-02 Snipe-IT is the system of record for assignments. The portal stores workflow state and evidence only. It is not a second asset inventory.
- BIZ-03 Physical reality is the reference. The engineer works from the physical device and the report; Snipe-IT is corrected as a consequence of verified handovers.
- BIZ-04 Paper signature is mandatory. No electronic signature is implemented or suggested. The signed sheet is scanned and stored as evidence.
- BIZ-05 "Done" means verified. A stage that touches Snipe-IT passes only after the portal re-reads Snipe-IT and sees the expected state. Pressing a button is not proof.
- BIZ-06 A handover is `completed` only when all nine stages are `passed`.

## The nine stages (fixed order)
`device_prepared` → `user_signed_in` → `agent_report` → `recipient_check` → `checkout` → `report_printed` → `user_signed` → `document_scanned` → `document_pushed`.
Dependencies: 2←1; 3←1; 4←3; 5←4; 6←3; 7←6; 8←7; 9←8.

## Rules
- BIZ-07 The agent report's serial must equal the handover's device serial; otherwise stage 3 is `failed` with a clear reason.
- BIZ-08 The recipient is the Snipe-IT user explicitly confirmed by the engineer. If the user does not exist in Snipe-IT, stage 4 is `blocked` ("Recipient not found in Snipe-IT"), the handover is `stalled`, and the dashboard names the missing step. The portal never creates users.
- BIZ-09 The signed sheet is attached to the DEVICE (the Snipe-IT asset), never to the user. It does not depend on the recipient: stage 9 needs only the stored scan (stage 8) and an existing asset. If the asset serial is unknown in Snipe-IT, stage 9 is `failed` with that reason.
- BIZ-10 If the detected recipient equals the engineer's own account, the portal warns (the script may have run elevated) and forces an explicit choice.
- BIZ-11 An asset assigned to someone else is never taken over silently: stage 5 fails and names the current holder.
- BIZ-12 Old devices of the recipient are checked in only by an explicit per-device engineer decision (a device may be kept, for example during a temporary swap).
- BIZ-13 Only one active handover per device serial.
- BIZ-14 Status is derived: `cancelled` explicit; `completed` all passed; `stalled` any `failed`/`blocked`; `draft` all pending; else `in_progress`. The time-based "no progress for N days" rule is an open decision and is not implemented.
- BIZ-15 The dashboard shows completed versus not-yet-completed handovers and, for each incomplete one, exactly what is missing and why.
- BIZ-16 Out of scope until the owner decides: Lab Care ticket integration, QR/mailbox scan automation, daily reconciliation dashboard, GPO logon reporting, per-engineer OAuth.
