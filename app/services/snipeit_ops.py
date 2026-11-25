"""Snipe-IT-backed handover operations (Phase 5).

Recipient lookup/confirmation, per-asset checkin, and the verified checkout
that passes stage 5. Every method is idempotent where the workflow requires
it and records one event per attempt, success or failure.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app import config
from app.clients.snipeit import (
    SnipeItAsset,
    SnipeItAuthError,
    SnipeItClient,
    SnipeItError,
    SnipeItNotFound,
    SnipeItRejected,
    SnipeItUnavailable,
)
from app.db.models.handover import Handover
from app.domain.errors import (
    CaseStateConflict,
    CompanyMismatch,
    InputMissing,
    RecipientConfirmationConflict,
)
from app.domain.company_rules import company_conflict, company_known
from app.domain.recipient_identity import DetectedUser, detect_recipient
from app.domain.stages import Operation, StageStatus
from app.dto.handover import (
    CheckinOutcome,
    HandoverPreview,
    PreviewCall,
    RecipientCandidate,
    RecipientSearchResult,
)
from app.repositories.events import EventRepository
from app.services.handovers import (
    HandoverDetailView,
    HandoverService,
    ensure_open,
    stage_row,
)

RECIPIENT_NOT_FOUND_REASON = "Recipient not found in Snipe-IT"
ASSET_NOT_FOUND_REASON = "Asset serial not found in Snipe-IT"
VERIFICATION_FAILED_REASON = (
    "Verification failed: the asset is not assigned to the confirmed recipient."
)
ELEVATED_AGENT_WARNING = (
    "The agent reported the engineer's own account. The agent may have been "
    "run elevated; choose the recipient explicitly."
)

# The Snipe-IT status label used for each maintenance state. Empty means the
# owner has not configured that label; the flow stays non-blocking.
_MAINTENANCE_LABEL_SETTINGS = {
    "needs_maintenance": "SNIPEIT_STATUS_NEEDS_MAINTENANCE",
    "in_maintenance": "SNIPEIT_STATUS_IN_MAINTENANCE",
    "returned": "SNIPEIT_STATUS_RETURNED",
}


class SnipeItHandoverService:
    """Snipe-IT operations for one handover, all inside the caller's session."""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._core = HandoverService(session)
        self._events = EventRepository(session)

    # -- recipient --------------------------------------------------------
    async def search_recipients(
        self,
        handover_id: uuid.UUID,
        query: str | None,
        *,
        client: SnipeItClient,
        engineer_email: str,
        engineer_name: str = "",
    ) -> RecipientSearchResult:
        handover = await self._core.get(handover_id, with_details=True)
        report = await self._core.latest_agent_report(handover_id)
        detected = (
            detect_recipient(report.payload, handover.engineer_email)
            if report is not None
            else DetectedUser("", None, "", True, False)
        )
        manual_query = (query or "").strip()
        search_query = manual_query or detected.sam
        if not manual_query and (detected.is_local or not detected.sam):
            return RecipientSearchResult(
                query="",
                candidates=[],
                reported_username=handover.recipient_reported_username,
                warning="Cannot determine a domain user on this device — search manually",
                detected_user=detected.raw or None,
                is_local=detected.is_local,
                same_as_engineer=detected.same_as_engineer,
            )
        if not search_query:
            return RecipientSearchResult(
                query="",
                candidates=[],
                reported_username=handover.recipient_reported_username,
                detected_user=detected.raw or None,
                is_local=detected.is_local,
                same_as_engineer=detected.same_as_engineer,
            )
        users = await client.search_users(search_query)
        engineer_keys = _identity_keys(engineer_email, engineer_name)
        reported = handover.recipient_reported_username
        reported_key = (reported or "").strip().casefold()

        candidates = [
            RecipientCandidate(
                id=user.id,
                username=user.username,
                name=user.name,
                email=user.email,
                matches_reported=bool(reported_key)
                and reported_key in _user_keys(user),
                matches_engineer=bool(engineer_keys & _user_keys(user)),
            )
            for user in users
        ]

        warning = None
        if detected.same_as_engineer or (reported_key and reported_key in engineer_keys):
            warning = ELEVATED_AGENT_WARNING

        return RecipientSearchResult(
            query=search_query,
            candidates=candidates,
            reported_username=reported,
            warning=warning,
            detected_user=detected.raw or None,
            is_local=detected.is_local,
            same_as_engineer=detected.same_as_engineer,
        )

    async def choose_recipient(
        self,
        handover_id: uuid.UUID,
        *,
        mode: str,
        user_id: int | None = None,
        name: str | None = None,
        email: str | None = None,
        actor: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        """Store one of the three supported recipient choices."""
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)

        checkout_row = stage_row(handover, Operation.CHECKOUT)
        if checkout_row.status == StageStatus.PASSED.value:
            raise CaseStateConflict("The device is already checked out.")

        old_name = (
            handover.recipient_snipeit_name
            or handover.recipient_snipeit_username
            or handover.recipient_free_name
            or ""
        )
        user = None
        if mode == "snipeit":
            assert user_id is not None
            user = await client.get_user(user_id)
            if company_conflict(handover.device_company, user.company):
                raise CompanyMismatch()

        new_name = ""
        detail: dict[str, Any]
        status: StageStatus
        reason: str | None
        if mode == "snipeit":
            assert user is not None
            new_name = user.name or user.username or ""
            detail = {
                "snipeit_user_id": user.id,
                "username": user.username,
                "name": user.name,
            }
            if not company_known(user.company):
                detail["warning"] = "company_unknown"
            status = StageStatus.PASSED
            reason = None
        elif mode == "none":
            detail = {}
            status = StageStatus.NOT_DONE
            reason = "No recipient yet"
        else:
            new_name = (name or "").strip()
            detail = {"name": new_name, "email": (email or "").strip()}
            status = StageStatus.NOT_DONE
            reason = "Not in Snipe-IT yet"

        self._clear_recipient_fields(handover)
        handover.recipient_mode = mode
        if mode == "snipeit":
            assert user is not None
            handover.recipient_snipeit_id = user.id
            handover.recipient_snipeit_username = user.username
            handover.recipient_snipeit_name = user.name
            handover.recipient_snipeit_email = user.email
            handover.recipient_confirmed_by = actor
            handover.recipient_confirmed_at = _utcnow()
        elif mode == "not_in_snipeit":
            handover.recipient_free_name = new_name
            handover.recipient_free_email = (email or "").strip()

        items_row = stage_row(handover, Operation.RECIPIENT_ITEMS)
        if items_row.status == StageStatus.PASSED.value:
            items_row.status = StageStatus.PENDING.value
            items_row.reason = None
            items_row.detail = {}
            items_row.actor = None
            items_row.updated_at = _utcnow()

        await self._session.flush()
        if old_name != new_name:
            await self._events.add(
                handover_id=handover.id,
                actor=actor,
                type="recipient_changed",
                detail={"old_name": old_name, "new_name": new_name},
            )

        view = await self._core.record_operation(
            handover.id,
            Operation.RECIPIENT_CHECK,
            status=status,
            reason=reason,
            detail=detail,
            actor=actor,
            input_checks=False,
        )
        if mode == "snipeit":
            items = await self._recipient_items(handover, client=client)
            if not items:
                view = await self._core.record_operation(
                    handover.id,
                    Operation.RECIPIENT_ITEMS,
                    status=StageStatus.PASSED,
                    reason=None,
                    detail={"none": True},
                    actor=actor,
                    input_checks=False,
                )
        return view

    async def list_recipient_items(
        self,
        handover_id: uuid.UUID,
        *,
        client: SnipeItClient,
    ) -> list[dict[str, Any]]:
        """List the selected recipient's current assets, excluding this case."""
        handover = await self._core.get(handover_id, with_details=True)
        if handover.recipient_mode != "snipeit" or handover.recipient_snipeit_id is None:
            return []
        return await self._recipient_items(handover, client=client)

    async def checkin_recipient_items(
        self,
        handover_id: uuid.UUID,
        asset_ids: list[int],
        *,
        actor: str,
        client: SnipeItClient,
    ) -> list[CheckinOutcome]:
        """Check in assets only when they belong to the selected recipient."""
        handover = await self._core.get(handover_id, with_details=True)
        items = await self.list_recipient_items(handover_id, client=client)
        owned_ids = {item["asset_id"] for item in items}
        invalid_ids = [asset_id for asset_id in asset_ids if asset_id not in owned_ids]
        if invalid_ids:
            raise InputMissing(
                "Only the recipient's current items can be checked in."
            )
        outcomes = await self.checkin_assets(
            handover_id, asset_ids, actor=actor, client=client
        )
        row = stage_row(handover, Operation.RECIPIENT_ITEMS)
        checked_in = list((row.detail or {}).get("checked_in", []))
        for outcome in outcomes:
            if outcome.status == "checked_in" and outcome.serial:
                if outcome.serial not in checked_in:
                    checked_in.append(outcome.serial)
        row.detail = {**(row.detail or {}), "checked_in": checked_in}
        await self._session.flush()
        return outcomes

    async def confirm_recipient_items(
        self,
        handover_id: uuid.UUID,
        *,
        actor: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        """Pass recipient-items after checking in selected assets."""
        handover = await self._core.get(handover_id, with_details=True)
        row = stage_row(handover, Operation.RECIPIENT_ITEMS)
        items = await self.list_recipient_items(handover_id, client=client)
        detail = {
            "checked_in": list((row.detail or {}).get("checked_in", [])),
            "kept": [item["serial"] for item in items if item["serial"]],
        }
        return await self._core.record_operation(
            handover.id,
            Operation.RECIPIENT_ITEMS,
            status=StageStatus.PASSED,
            reason=None,
            detail=detail,
            actor=actor,
            input_checks=False,
        )

    async def _recipient_items(
        self, handover: Handover, *, client: SnipeItClient
    ) -> list[dict[str, Any]]:
        recipient_id = handover.recipient_snipeit_id
        if recipient_id is None:
            return []
        assets = await client.list_user_assets(recipient_id)
        return [
            {
                "asset_id": asset.id,
                "asset_tag": asset.asset_tag,
                "serial": asset.serial,
                "model": asset.model,
                "status": asset.status,
            }
            for asset in assets
            if asset.id != handover.snipeit_asset_id
            and asset.serial != handover.device_serial
        ]

    @staticmethod
    def _clear_recipient_fields(handover: Handover) -> None:
        handover.recipient_snipeit_id = None
        handover.recipient_snipeit_username = None
        handover.recipient_snipeit_name = None
        handover.recipient_snipeit_email = None
        handover.recipient_free_name = None
        handover.recipient_free_email = None
        handover.recipient_confirmed_by = None
        handover.recipient_confirmed_at = None

    async def confirm_recipient(
        self,
        handover_id: uuid.UUID,
        *,
        snipeit_user_id: int | None,
        not_found: bool,
        actor: str,
        client: SnipeItClient,
        acknowledge_same_as_engineer: bool = False,
    ) -> HandoverDetailView:
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)

        report = await self._core.latest_agent_report(handover.id)
        detected = (
            detect_recipient(report.payload, handover.engineer_email)
            if report is not None
            else None
        )
        row = stage_row(handover, Operation.RECIPIENT_CHECK)
        if row.status == StageStatus.PASSED.value:
            if (
                snipeit_user_id is not None
                and handover.recipient_snipeit_id == snipeit_user_id
            ):
                return await self._core.view(handover)
            raise CaseStateConflict(
                "Recipient already confirmed; reopen the operation first."
            )

        if not_found:
            return await self._block_recipient(handover, actor=actor)

        if (
            detected is not None
            and detected.same_as_engineer
            and not acknowledge_same_as_engineer
        ):
            raise RecipientConfirmationConflict(
                "The detected user matches the engineer. Confirm with explicit acknowledgement."
            )

        assert snipeit_user_id is not None  # enforced by the DTO
        try:
            user = await client.get_user(snipeit_user_id)
        except SnipeItNotFound:
            return await self._block_recipient(handover, actor=actor)

        handover.recipient_snipeit_id = user.id
        handover.recipient_snipeit_username = user.username or user.name
        handover.recipient_snipeit_name = user.name
        handover.recipient_snipeit_email = user.email
        handover.recipient_confirmed_by = actor
        handover.recipient_confirmed_at = _utcnow()
        await self._session.flush()

        return await self._core.record_operation(
            handover.id,
            Operation.RECIPIENT_CHECK,
            status=StageStatus.PASSED,
            reason=None,
            detail={
                "snipeit_user_id": user.id,
                "username": user.username,
                "name": user.name,
            },
            actor=actor,
            input_checks=False,
        )

    async def _block_recipient(
        self, handover: Handover, *, actor: str
    ) -> HandoverDetailView:
        handover.recipient_snipeit_id = None
        handover.recipient_snipeit_username = None
        handover.recipient_snipeit_name = None
        handover.recipient_snipeit_email = None
        handover.recipient_confirmed_by = actor
        handover.recipient_confirmed_at = _utcnow()
        await self._session.flush()

        return await self._core.record_operation(
            handover.id,
            Operation.RECIPIENT_CHECK,
            status=StageStatus.FAILED,
            reason=RECIPIENT_NOT_FOUND_REASON,
            detail={
                "not_found": True,
                "reported_username": handover.recipient_reported_username,
            },
            actor=actor,
            input_checks=False,
        )

    # -- dry run ----------------------------------------------------------
    async def preview(
        self, handover_id: uuid.UUID, *, client: SnipeItClient
    ) -> HandoverPreview:
        handover = await self._core.get(handover_id, with_details=True)
        checkout_row = stage_row(handover, Operation.CHECKOUT)
        already_passed = checkout_row.status == StageStatus.PASSED.value
        recipient_id = handover.recipient_snipeit_id

        calls: list[PreviewCall] = []
        warnings: list[str] = []
        asset: SnipeItAsset | None = None

        if already_passed:
            warnings.append(
                "Checkout already passed; no checkout call would be made."
            )
        if recipient_id is None:
            warnings.append(
                "Recipient is not confirmed; no checkout call would be made."
            )
        else:
            try:
                asset = await client.get_asset_by_serial(
                    handover.device_serial
                )
            except SnipeItNotFound:
                warnings.append(
                    "Asset serial not found in Snipe-IT; no checkout call "
                    "would be made."
                )
            except SnipeItError as exc:
                warnings.append(f"Could not read the asset: {exc}")

            if asset is not None and not already_passed:
                holder = _holder_label(asset)
                if asset.assigned_to_id == recipient_id:
                    warnings.append(
                        "Device is already assigned to the confirmed "
                        "recipient; checkout would be skipped."
                    )
                elif asset.assigned_to_id is not None:
                    warnings.append(
                        f"Device is currently assigned to {holder}; no "
                        "checkout call would be made."
                    )
                else:
                    calls.append(
                        PreviewCall(
                            action="checkout",
                            asset_id=asset.id,
                            asset_tag=asset.asset_tag,
                            serial=asset.serial,
                            target_user_id=recipient_id,
                            target_user_name=(
                                handover.recipient_snipeit_username
                            ),
                            description=(
                                f"Checkout asset {asset.asset_tag or asset.id}"
                                f" ({asset.serial or 'no serial'}) to "
                                f"{handover.recipient_snipeit_username or recipient_id}"
                            ),
                        )
                    )

            if recipient_id is not None:
                try:
                    old_assets = await client.list_user_assets(recipient_id)
                except SnipeItError as exc:
                    warnings.append(
                        f"Could not list the recipient's current assets: {exc}"
                    )
                    old_assets = []
                for old in old_assets:
                    if asset is not None and old.id == asset.id:
                        continue
                    if old.serial == handover.device_serial:
                        continue
                    calls.append(
                        PreviewCall(
                            action="checkin",
                            asset_id=old.id,
                            asset_tag=old.asset_tag,
                            serial=old.serial,
                            target_user_id=recipient_id,
                            target_user_name=(
                                handover.recipient_snipeit_username
                            ),
                            description=(
                                f"Checkin old asset "
                                f"{old.asset_tag or old.id} "
                                f"({old.serial or 'no serial'}) from "
                                f"{handover.recipient_snipeit_username or recipient_id}"
                            ),
                        )
                    )

        return HandoverPreview(
            handover_id=handover.id,
            checkout_stage_status=checkout_row.status,
            recipient_confirmed=recipient_id is not None,
            already_passed=already_passed,
            calls=calls,
            warnings=warnings,
        )

    # -- checkin ----------------------------------------------------------
    async def checkin_assets(
        self,
        handover_id: uuid.UUID,
        asset_ids: list[int],
        *,
        actor: str,
        client: SnipeItClient,
    ) -> list[CheckinOutcome]:
        handover = await self._core.get(handover_id, with_details=True)
        ensure_open(handover)
        recipient_id = handover.recipient_snipeit_id
        if recipient_id is None:
            raise InputMissing(
                "Pick a recipient first; there is nothing to check in."
            )

        outcomes: list[CheckinOutcome] = []
        for asset_id in asset_ids:
            outcome = await self._checkin_one(
                handover,
                asset_id,
                recipient_id=recipient_id,
                actor=actor,
                client=client,
            )
            outcomes.append(outcome)
        return outcomes

    async def _checkin_one(
        self,
        handover: Handover,
        asset_id: int,
        *,
        recipient_id: int,
        actor: str,
        client: SnipeItClient,
    ) -> CheckinOutcome:
        try:
            asset = await client.get_asset(asset_id)
        except SnipeItError as exc:
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset_id,
                    status="not_found"
                    if isinstance(exc, SnipeItNotFound)
                    else "failed",
                    message=str(exc),
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if asset.id == handover.snipeit_asset_id or (
            asset.serial == handover.device_serial
        ):
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset.id,
                    status="refused_handover_device",
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    message=(
                        "This is the handover device; it is never checked in "
                        "by this action."
                    ),
                ),
                actor=actor,
            )

        if asset.assigned_to_id is None:
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset.id,
                    status="already_unassigned",
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    message="Asset is already unassigned.",
                ),
                actor=actor,
            )

        if asset.assigned_to_id != recipient_id:
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset.id,
                    status="not_recipient",
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    message=(
                        "Asset is assigned to "
                        f"{_holder_label(asset)}; refusing to check in."
                    ),
                ),
                actor=actor,
            )

        note = (
            f"Handover by {actor} via Handover Portal, "
            f"case {handover.id}"
        )
        try:
            result = await client.checkin_asset(asset.id, note)
            verified = await client.get_asset(asset.id)
        except SnipeItError as exc:
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset.id,
                    status="failed",
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    message=str(exc),
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if verified.assigned_to_id is not None:
            return await self._checkin_outcome(
                handover,
                CheckinOutcome(
                    asset_id=asset.id,
                    status="verification_failed",
                    asset_tag=asset.asset_tag,
                    serial=asset.serial,
                    message="Asset is still assigned after the checkin.",
                ),
                actor=actor,
                detail={"snipeit_status": result.status_code},
            )

        return await self._checkin_outcome(
            handover,
            CheckinOutcome(
                asset_id=asset.id,
                status="checked_in",
                asset_tag=asset.asset_tag,
                serial=asset.serial,
                message=result.message,
            ),
            actor=actor,
            detail={"snipeit_status": result.status_code},
        )

    async def _checkin_outcome(
        self,
        handover: Handover,
        outcome: CheckinOutcome,
        *,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> CheckinOutcome:
        payload: dict[str, Any] = {
            "asset_id": outcome.asset_id,
            "outcome": outcome.status,
            "message": outcome.message,
        }
        payload.update(detail or {})
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="checkin_attempt",
            detail=payload,
        )
        return outcome

    # -- checkout ---------------------------------------------------------
    async def checkout(
        self,
        handover_id: uuid.UUID,
        *,
        actor: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        handover = await self._core.get(handover_id, with_details=True)
        row = stage_row(handover, Operation.CHECKOUT)
        if row.status == StageStatus.PASSED.value:
            return await self._core.view(handover)

        ensure_open(handover)

        recipient_id = handover.recipient_snipeit_id
        if recipient_id is None:
            raise InputMissing(
                "Pick a recipient first, or mark Checkout as not done."
            )

        try:
            asset = await client.get_asset_by_serial(
                handover.device_serial
            )
        except SnipeItError as exc:
            return await self._fail_checkout(
                handover,
                reason=(
                    ASSET_NOT_FOUND_REASON
                    if isinstance(exc, SnipeItNotFound)
                    else snipeit_error_reason(exc)
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        handover.snipeit_asset_id = asset.id
        handover.snipeit_asset_tag = asset.asset_tag

        if asset.assigned_to_id == recipient_id:
            return await self._pass_checkout(
                handover,
                asset,
                actor=actor,
                already_assigned=True,
                snipeit_status=None,
            )

        if asset.assigned_to_id is not None:
            return await self._fail_checkout(
                handover,
                reason=(
                    "Device is currently assigned to "
                    f"{_holder_label(asset)}; no checkout was made."
                ),
                actor=actor,
                detail={
                    "asset_id": asset.id,
                    "assigned_to_id": asset.assigned_to_id,
                    "assigned_to_name": asset.assigned_to_name,
                },
            )

        note = (
            f"Handover by {actor} via Handover Portal, "
            f"case {handover.id}"
        )
        try:
            result = await client.checkout_asset_to_user(
                asset.id, recipient_id, note
            )
        except SnipeItError as exc:
            return await self._fail_checkout(
                handover,
                reason=snipeit_error_reason(exc),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if result.status != "success":
            return await self._fail_checkout(
                handover,
                reason=(
                    result.message or "Snipe-IT did not confirm the checkout."
                ),
                actor=actor,
                detail={"snipeit_status": result.status_code},
            )

        try:
            verified = await client.get_asset(asset.id)
        except SnipeItError as exc:
            return await self._fail_checkout(
                handover,
                reason=(
                    "Verification failed: the asset could not be re-read "
                    "after checkout."
                ),
                actor=actor,
                detail=snipeit_error_detail(exc),
            )

        if verified.assigned_to_id != recipient_id:
            return await self._fail_checkout(
                handover,
                reason=VERIFICATION_FAILED_REASON,
                actor=actor,
                detail={
                    "expected_user_id": recipient_id,
                    "actual_user_id": verified.assigned_to_id,
                    "snipeit_status": result.status_code,
                },
            )

        return await self._pass_checkout(
            handover,
            verified,
            actor=actor,
            already_assigned=False,
            snipeit_status=result.status_code,
        )

    async def _pass_checkout(
        self,
        handover: Handover,
        asset: SnipeItAsset,
        *,
        actor: str,
        already_assigned: bool,
        snipeit_status: int | None,
    ) -> HandoverDetailView:
        row = stage_row(handover, Operation.CHECKOUT)
        row.status = StageStatus.PASSED.value
        row.reason = None
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = {
            "asset_id": asset.id,
            "asset_tag": asset.asset_tag,
            "assigned_to_id": asset.assigned_to_id,
            "already_assigned": already_assigned,
        }
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="checkout_attempt",
            detail={
                "asset_id": asset.id,
                "outcome": "already_assigned"
                if already_assigned
                else "checked_out",
                "assigned_to_id": asset.assigned_to_id,
                "snipeit_status": snipeit_status,
            },
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    async def _fail_checkout(
        self,
        handover: Handover,
        *,
        reason: str,
        actor: str,
        detail: dict[str, Any] | None = None,
    ) -> HandoverDetailView:
        row = stage_row(handover, Operation.CHECKOUT)
        row.status = StageStatus.FAILED.value
        row.reason = reason
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = detail or {}
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="checkout_attempt",
            detail={"outcome": "failed", "reason": reason, **(detail or {})},
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)


    # -- maintenance status label ---------------------------------------------

    # -- device status ----------------------------------------------------
    async def set_device_status(
        self,
        handover_id: uuid.UUID,
        *,
        status_label_id: int | None,
        actor: str,
        client: SnipeItClient,
    ) -> HandoverDetailView:
        """Set the device's Snipe-IT status and record the device-status part.

        The part passes when the device ends on the ready status label. A
        Snipe-IT error is recorded as a failed part, never raised.
        """
        handover = await self._core.get(handover_id, with_details=True)

        if status_label_id is not None:
            try:
                result = await client.update_asset_status(
                    handover.snipeit_asset_id or 0, status_label_id
                )
            except SnipeItError as exc:
                return await self._core.record_operation(
                    handover_id,
                    Operation.DEVICE_STATUS,
                    status=StageStatus.FAILED,
                    reason=snipeit_error_reason(exc),
                    detail=snipeit_error_detail(exc),
                    actor=actor,
                )
            if result.status != "success":
                return await self._core.record_operation(
                    handover_id,
                    Operation.DEVICE_STATUS,
                    status=StageStatus.FAILED,
                    reason="Snipe-IT rejected the status change.",
                    detail={"status_label_id": status_label_id},
                    actor=actor,
                )

        try:
            asset = await client.get_asset_by_serial(handover.device_serial)
        except SnipeItError as exc:
            return await self._core.record_operation(
                handover_id,
                Operation.DEVICE_STATUS,
                status=StageStatus.FAILED,
                reason=snipeit_error_reason(exc),
                detail=snipeit_error_detail(exc),
                actor=actor,
            )

        handover.snipeit_asset_id = asset.id
        handover.snipeit_asset_tag = asset.asset_tag
        handover.device_company = asset.company
        handover.device_model = asset.model
        handover.device_category = asset.category
        handover.snipeit_status_name = asset.status
        await self._session.flush()

        ready = str(config.SNIPEIT_STATUS_READY or "").strip().casefold()
        current = str(asset.status or "").strip().casefold()
        passed = bool(ready) and current == ready
        return await self._core.record_operation(
            handover_id,
            Operation.DEVICE_STATUS,
            status=StageStatus.PASSED if passed else StageStatus.FAILED,
            reason=None if passed else f"Status is {asset.status}",
            detail={
                "status": asset.status,
                "status_label_id": status_label_id,
                "company": asset.company,
            },
            actor=actor,
        )

    async def update_maintenance_status(
        self,
        handover_id: uuid.UUID,
        *,
        actor: str,
        client: SnipeItClient,
    ) -> dict[str, Any]:
        """Move the asset to the Snipe-IT status label of its state.

        Never raises: the transit operation itself stays authoritative. The
        result tells the UI whether the label was updated and why not.
        """
        handover = await self._core.get(handover_id, with_details=True)
        state = handover.maintenance_state or "needs_maintenance"
        setting = _MAINTENANCE_LABEL_SETTINGS.get(state)
        label = getattr(config, setting, "") if setting else ""
        if not label:
            return {"updated": False, "reason": "label_not_configured"}
        if not handover.snipeit_asset_id:
            return {"updated": False, "reason": "no_snipeit_asset"}
        try:
            labels = await client.list_status_labels()
        except SnipeItError as exc:
            return {"updated": False, "reason": snipeit_error_reason(exc)}
        match = next(
            (
                status_id
                for status_id, name in labels
                if name.casefold() == str(label).casefold()
            ),
            None,
        )
        if match is None:
            return {"updated": False, "reason": "label_not_found"}
        try:
            result = await client.update_asset_status(
                handover.snipeit_asset_id, match
            )
        except SnipeItError as exc:
            return {"updated": False, "reason": snipeit_error_reason(exc)}
        if result.status != "success":
            return {"updated": False, "reason": "snipeit_rejected"}
        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="snipeit_status_label_updated",
            detail={"state": state, "label": label},
        )
        return {"updated": True, "reason": None}


def _identity_keys(email: str, name: str) -> set[str]:
    keys: set[str] = set()
    cleaned_email = (email or "").strip().casefold()
    if cleaned_email:
        keys.add(cleaned_email)
        keys.add(cleaned_email.split("@")[0])
    cleaned_name = (name or "").strip().casefold()
    if cleaned_name:
        keys.add(cleaned_name)
    return keys


def _user_keys(user: Any) -> set[str]:
    keys = {
        str(value).strip().casefold()
        for value in (user.username, user.email, user.name)
        if value
    }
    for value in (user.email, user.username):
        if value and "@" in str(value):
            keys.add(str(value).split("@")[0].strip().casefold())
    return keys


def _holder_label(asset: SnipeItAsset) -> str:
    if asset.assigned_to_name:
        return asset.assigned_to_name
    if asset.assigned_to_id is not None:
        return f"user {asset.assigned_to_id}"
    return "someone else"


def snipeit_error_reason(exc: SnipeItError) -> str:
    if isinstance(exc, SnipeItUnavailable):
        return "Could not reach Snipe-IT."
    if isinstance(exc, SnipeItAuthError):
        return "Snipe-IT rejected the credentials."
    if isinstance(exc, SnipeItNotFound):
        return ASSET_NOT_FOUND_REASON
    if isinstance(exc, SnipeItRejected):
        return str(exc)
    return str(exc)


def snipeit_error_detail(exc: SnipeItError) -> dict[str, Any]:
    return {
        "error": type(exc).__name__,
        "snipeit_status": getattr(exc, "status_code", None),
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

