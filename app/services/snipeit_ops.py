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
from app.domain.errors import RecipientConfirmationConflict, StageNotRunnable
from app.domain.handover_rules import can_run
from app.domain.recipient_identity import DetectedUser, detect_recipient
from app.domain.stages import Stage, StageStatus
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
    stage_states,
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
        row = stage_row(handover, Stage.RECIPIENT_CHECK)
        if row.status == StageStatus.PASSED.value:
            if (
                snipeit_user_id is not None
                and handover.recipient_snipeit_id == snipeit_user_id
            ):
                return await self._core.view(handover)
            raise StageNotRunnable("Recipient already confirmed.")

        allowed, reason = can_run(Stage.RECIPIENT_CHECK, stage_states(handover))
        if not allowed:
            raise StageNotRunnable(reason)

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
        handover.recipient_confirmed_by = actor
        handover.recipient_confirmed_at = _utcnow()

        row.status = StageStatus.PASSED.value
        row.reason = None
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = {
            "snipeit_user_id": user.id,
            "username": user.username,
            "name": user.name,
        }

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="recipient_confirmed",
            detail={
                "snipeit_user_id": user.id,
                "username": user.username,
                "reported_username": handover.recipient_reported_username,
            },
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    async def _block_recipient(
        self, handover: Handover, *, actor: str
    ) -> HandoverDetailView:
        handover.recipient_snipeit_id = None
        handover.recipient_snipeit_username = None
        handover.recipient_confirmed_by = actor
        handover.recipient_confirmed_at = _utcnow()

        row = stage_row(handover, Stage.RECIPIENT_CHECK)
        row.status = StageStatus.BLOCKED.value
        row.reason = RECIPIENT_NOT_FOUND_REASON
        row.actor = actor
        row.updated_at = _utcnow()
        row.detail = {
            "not_found": True,
            "reported_username": handover.recipient_reported_username,
        }

        await self._events.add(
            handover_id=handover.id,
            actor=actor,
            type="recipient_not_found",
            detail={"reason": RECIPIENT_NOT_FOUND_REASON},
        )
        await self._core.recompute_status(handover)
        return await self._core.view(handover)

    # -- dry run ----------------------------------------------------------
    async def preview(
        self, handover_id: uuid.UUID, *, client: SnipeItClient
    ) -> HandoverPreview:
        handover = await self._core.get(handover_id, with_details=True)
        checkout_row = stage_row(handover, Stage.CHECKOUT)
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
            raise StageNotRunnable(
                "Recipient is not confirmed; there is nothing to check in."
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
        row = stage_row(handover, Stage.CHECKOUT)
        if row.status == StageStatus.PASSED.value:
            return await self._core.view(handover)

        ensure_open(handover)
        allowed, reason = can_run(Stage.CHECKOUT, stage_states(handover))
        if not allowed:
            raise StageNotRunnable(reason)

        recipient_id = handover.recipient_snipeit_id
        if recipient_id is None:
            raise StageNotRunnable("Recipient is not confirmed.")

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
        row = stage_row(handover, Stage.CHECKOUT)
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
        row = stage_row(handover, Stage.CHECKOUT)
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

