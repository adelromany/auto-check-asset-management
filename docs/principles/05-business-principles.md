# 05 — Business Principles

## Vocabulary (use exactly these words in code, API, DB, UI)
- BIZ-01 **Handover**: one case of giving one device to one employee. **Checkout**: assign an asset to a user in Snipe-IT. **Checkin**: return an asset from a user in Snipe-IT. **Recipient**: the employee receiving the device. **Engineer**: the IT person performing the handover (SSO identity). **Operation**: one recordable step of a case. The old word **Stage** remains an alias in code and API paths. **Maintenance case**: one case of tracking a device through repair and maintenance. **Vendor**: a company responsible for repairing devices (synonym of destination in API and storage). **Maintenance state**: derived device state among `needs_maintenance`, `in_maintenance`, and `returned`.

## Principles
- BIZ-02 Snipe-IT is the system of record for assignments. The portal stores workflow state and evidence only. It is not a second asset inventory.
- BIZ-03 Physical reality is the reference. The engineer works from the physical device and the report; Snipe-IT is corrected as a consequence of verified handovers.
- BIZ-04 Paper signature is mandatory. No electronic signature is implemented or suggested. The signed sheet is scanned and stored as evidence.
- BIZ-05 "Done" means verified. A stage that touches Snipe-IT passes only after the portal re-reads Snipe-IT and sees the expected state. Pressing a button is not proof.
- BIZ-06 A handover is `completed` only when every operation is `passed`. Only `passed` counts as done; `not_done` never completes a case.

## The ten handover operations (reading order, not a gate)
`device_prepared` → `user_signed_in` → `agent_report` → `software_check` → `recipient_check` → `checkout` → `report_printed` → `user_signed` → `document_scanned` → `document_pushed`.

## The five maintenance operations (grouped into Intake, Status, Transit)
`received` → `diagnosis` → `snipeit_status` → `sent_out` → `returned`.

BIZ-19 Operations are independent. The arrows above, and the `RECOMMENDED_AFTER` map, are advice only: any operation can be recorded at any time. Starting an operation before a recommended predecessor is allowed and stores an `advice`/`performed_before` note on that outcome. Nothing returns "Waiting for …".

## Rules
- BIZ-07 The agent report must match the handover serial and include CPU, positive RAM, and at least one disk; otherwise `agent_report` is `failed` with a reason for every missing or mismatched item. Hardware and software are evaluated independently: a report failure never prevents the software result from being recorded.
- BIZ-18 `software_check` requires every configured software id to be reported installed and Windows activation status code 1. A failed check can be marked `not_done` only through the authenticated override with an audit reason.
- BIZ-08 The recipient is the Snipe-IT user explicitly confirmed by the engineer. If the user does not exist in Snipe-IT, `recipient_check` is `failed` ("Recipient not found in Snipe-IT"); other operations can still run and the dashboard names the gap. The portal never creates users.
- BIZ-09 The signed sheet is attached to the DEVICE (the Snipe-IT asset), never to the user. It does not wait for the recipient or the paper signature: `document_pushed` needs only the stored scan and an existing asset. If the asset serial is unknown in Snipe-IT, it is `failed` with that reason.
- BIZ-20 `not_done` is an explicit engineer decision with a mandatory reason (3–300 characters) and stays visible as a gap. `failed` means the attempt was made and can be retried. A case can be `closed_with_gaps` only after typing the literal `CLOSE`; its gap list is stored, and only such a case can be reopened. Neither `failed` nor `not_done` blocks another operation.
- BIZ-21 Maintenance states are derived solely from transit operations: `returned` passed yields `returned`; `sent_out` passed yields `in_maintenance`; otherwise `needs_maintenance`. Failed or not-done attempts never advance the device state.
- BIZ-22 Turnaround time is calculated as `returned_date - sent_date` in days. A case is overdue when it is not yet returned and `today > due_date`, where due date is `expected_return_date` or defaults to 14 days after `sent_date`.
- BIZ-23 Governed lists: repair destinations and vendors (`FixTech`) and diagnosis categories (`Screen`, `Battery`, `Keyboard`, `Motherboard`, `Software`, `Other`) are governed database lists and never hardcoded strings.
- BIZ-10 If the detected recipient equals the engineer's own account, the portal warns (the script may have run elevated) and forces an explicit choice.
- BIZ-11 An asset assigned to someone else is never taken over silently: stage 5 fails and names the current holder.
- BIZ-12 Old devices of the recipient are checked in only by an explicit per-device engineer decision (a device may be kept, for example during a temporary swap).
- BIZ-13 Only one active handover per device serial.
- BIZ-14 Status is derived: `cancelled` and `closed_with_gaps` are explicit; `completed` when every operation is passed; `stalled` only when a draft/in-progress case has had no activity for `STALL_HOURS` (default 24, zero disables); `draft` when every operation is pending; else `in_progress`. A failure no longer stalls a case. The 24-hour value is PROPOSED pending owner approval (D-66).
- BIZ-15 The dashboard shows completed versus not-yet-completed handovers and, for each incomplete one, exactly what is missing and why. Implemented in Phase 7: `/handovers` (KPI tiles, filters, stage progress, Missing column) and `/handovers/{id}` (stage checklist and actions).
- BIZ-17 A dry-run preview (`GET /api/handovers/{id}/preview`) lists the Snipe-IT calls an engineer is about to make and performs no writes. The engineer still confirms each stage explicitly.
- BIZ-16 Out of scope until the owner decides: Lab Care ticket integration, QR/mailbox scan automation, daily reconciliation dashboard, GPO logon reporting, per-engineer OAuth.
