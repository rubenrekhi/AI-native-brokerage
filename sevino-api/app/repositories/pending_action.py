import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundError
from app.models.pending_action import (
    PendingAction,
    PendingActionStatus,
    effective_status,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PendingActionRepository:
    """Data access for human-in-the-loop pending actions.

    Mutating transitions are atomic compare-and-swaps guarded on
    ``status='pending'`` — the single mechanism that makes double-tap, expiry,
    and the supersede race safe (see docs/ai/hil-actions.md). Methods flush but
    never commit; the caller owns the transaction.
    """

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        action_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        agent_turn_id: uuid.UUID | None,
        tool_use_id: str,
        action_type: str,
        payload: dict[str, Any],
        preview: dict[str, Any],
        expires_at: datetime,
    ) -> PendingAction:
        row = PendingAction(
            id=action_id,
            user_id=user_id,
            conversation_id=conversation_id,
            agent_turn_id=agent_turn_id,
            tool_use_id=tool_use_id,
            action_type=action_type,
            payload=payload,
            preview=preview,
            status=PendingActionStatus.PENDING,
            expires_at=expires_at,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def get_owned(
        db: AsyncSession,
        *,
        action_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
    ) -> PendingAction:
        """Load an action scoped to its owner + conversation.

        Same ``NotFoundError`` for missing vs. wrong-owner — no existence leak.
        """
        row = (
            await db.execute(
                select(PendingAction).where(
                    PendingAction.id == action_id,
                    PendingAction.user_id == user_id,
                    PendingAction.conversation_id == conversation_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                "Action not found", resource="pending_action"
            )
        return row

    @staticmethod
    async def confirm(
        db: AsyncSession, *, action_id: uuid.UUID
    ) -> PendingAction | None:
        """Atomic CAS pending → confirmed. ``None`` if no longer confirmable."""
        return await PendingActionRepository._transition_from_pending(
            db,
            action_id=action_id,
            new_status=PendingActionStatus.CONFIRMED,
            timestamp_field="confirmed_at",
            require_unexpired=True,
        )

    @staticmethod
    async def reject(
        db: AsyncSession, *, action_id: uuid.UUID
    ) -> PendingAction | None:
        """Atomic CAS pending → rejected. ``None`` if no longer pending."""
        return await PendingActionRepository._transition_from_pending(
            db,
            action_id=action_id,
            new_status=PendingActionStatus.REJECTED,
            timestamp_field="rejected_at",
            require_unexpired=False,
        )

    @staticmethod
    async def supersede_pending_for_conversation(
        db: AsyncSession, *, conversation_id: uuid.UUID
    ) -> int:
        """Cancel every live proposal in a conversation; returns the count.

        Runs at the start of each user-initiated turn (any new message
        supersedes a hanging proposal). Already-expired rows are left as-is so
        the audit distinguishes "moved on" from "timed out".
        """
        now = _now()
        result = await db.execute(
            update(PendingAction)
            .where(
                PendingAction.conversation_id == conversation_id,
                PendingAction.status == PendingActionStatus.PENDING,
                PendingAction.expires_at > now,
            )
            .values(
                status=PendingActionStatus.SUPERSEDED, superseded_at=now
            )
            .returning(PendingAction.id)
        )
        return len(result.scalars().all())

    @staticmethod
    async def mark_executed(
        db: AsyncSession, *, action_id: uuid.UUID, result: dict[str, Any]
    ) -> None:
        # Guarded on ``confirmed`` so a stray double-call can't overwrite a
        # later state; only reached after a winning ``confirm`` CAS.
        await db.execute(
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == PendingActionStatus.CONFIRMED,
            )
            .values(
                status=PendingActionStatus.EXECUTED,
                executed_at=_now(),
                result=result,
            )
        )

    @staticmethod
    async def mark_failed(
        db: AsyncSession, *, action_id: uuid.UUID, result: dict[str, Any]
    ) -> None:
        await db.execute(
            update(PendingAction)
            .where(
                PendingAction.id == action_id,
                PendingAction.status == PendingActionStatus.CONFIRMED,
            )
            .values(status=PendingActionStatus.FAILED, result=result)
        )

    @staticmethod
    async def effective_statuses(
        db: AsyncSession, *, action_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Bulk effective_status for read-time confirmation-card resolution.

        Looks up by id only — the caller must pre-scope ``action_ids`` to the
        authenticated user (the GET-messages path sources them from that
        user's own owner-checked transcript).
        """
        if not action_ids:
            return {}
        now = _now()
        rows = await db.execute(
            select(
                PendingAction.id,
                PendingAction.status,
                PendingAction.expires_at,
            ).where(PendingAction.id.in_(action_ids))
        )
        return {
            row_id: effective_status(status, expires_at, now=now)
            for row_id, status, expires_at in rows
        }

    @staticmethod
    async def _transition_from_pending(
        db: AsyncSession,
        *,
        action_id: uuid.UUID,
        new_status: str,
        timestamp_field: str,
        require_unexpired: bool,
    ) -> PendingAction | None:
        now = _now()
        conditions = [
            PendingAction.id == action_id,
            PendingAction.status == PendingActionStatus.PENDING,
        ]
        if require_unexpired:
            conditions.append(PendingAction.expires_at > now)
        result = await db.execute(
            update(PendingAction)
            .where(*conditions)
            .values(status=new_status, **{timestamp_field: now})
            .returning(PendingAction.id)
        )
        if result.scalar_one_or_none() is None:
            return None
        # ``populate_existing`` overwrites any identity-mapped instance's
        # attributes with the freshly-updated row — the Core UPDATE above
        # bypasses the ORM, so without this a same-session caller would read
        # the stale pre-CAS status.
        return (
            await db.execute(
                select(PendingAction)
                .where(PendingAction.id == action_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
