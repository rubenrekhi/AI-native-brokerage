"""Hourly reconciliation of local `ach_relationships` against Alpaca state.

Funding state is otherwise pull-based (refresh-on-read in `GET
/v1/funding/ach-relationships` and `POST /v1/funding/transfers`). That
covers user-facing correctness but misses server-side cancellations and
silent transitions that happen while the user is away. This cron closes
that gap and gives ops a sync history for support triage. See SEV-580.
"""

import structlog

from app.database import async_session
from app.config import settings
from app.models.ach_relationship import AchRelationship
from app.repositories.ach_relationship import (
    STATUS_CANCELED,
    AchRelationshipRepository,
)
from app.repositories.brokerage_account import STATUS_ACTIVE
from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerService,
    AlpacaBrokerUnavailableError,
)

logger = structlog.get_logger(__name__)


async def reconcile_funding(ctx: dict) -> dict:
    if settings.is_pr_preview:
        logger.debug(
            "funding_reconcile_skipped_pr_preview",
            railway_env=settings.railway_environment_name,
        )
        return {"status": "skipped", "reason": "pr-preview"}

    alpaca: AlpacaBrokerService = ctx["alpaca"]

    checked = 0
    drifted = 0
    canceled_server_side = 0
    errored_accounts = 0

    async with async_session() as session:
        relationships = await AchRelationshipRepository.list_all_non_canceled(
            session
        )

        by_account: dict[str, list[AchRelationship]] = {}
        for rel in relationships:
            brokerage = rel.brokerage_account
            if brokerage is None or brokerage.account_status != STATUS_ACTIVE:
                continue
            by_account.setdefault(brokerage.alpaca_account_id, []).append(rel)

        for alpaca_account_id, rels in by_account.items():
            try:
                remote_list = await alpaca.list_ach_relationships(
                    alpaca_account_id
                )
            except (AlpacaBrokerError, AlpacaBrokerUnavailableError) as exc:
                errored_accounts += 1
                logger.warning(
                    "funding_reconcile_account_failed",
                    alpaca_account_id=alpaca_account_id,
                    error=str(exc),
                )
                continue

            remote_by_id = {r["id"]: r for r in remote_list}

            for rel in rels:
                checked += 1
                remote = remote_by_id.get(rel.alpaca_relationship_id)

                if remote is None:
                    # Alpaca dropped the relationship (compliance, fraud,
                    # account closure). Treat as a server-side cancellation
                    # and soft-delete locally to mirror unlink semantics.
                    canceled_server_side += 1
                    logger.info(
                        "funding_reconcile_drift",
                        kind="server_side_cancellation",
                        relationship_pk=str(rel.id),
                        user_id=str(rel.user_id),
                        alpaca_relationship_id=rel.alpaca_relationship_id,
                        status_from=rel.status,
                        status_to=STATUS_CANCELED,
                    )
                    rel.status = STATUS_CANCELED
                    continue

                new_status = remote.get("status")
                if new_status and new_status != rel.status:
                    drifted += 1
                    logger.info(
                        "funding_reconcile_drift",
                        kind="status_change",
                        relationship_pk=str(rel.id),
                        user_id=str(rel.user_id),
                        alpaca_relationship_id=rel.alpaca_relationship_id,
                        status_from=rel.status,
                        status_to=new_status,
                    )
                    rel.status = new_status

        await session.commit()

    result = {
        "status": "ok",
        "checked": checked,
        "drifted": drifted,
        "canceled_server_side": canceled_server_side,
        "errored_accounts": errored_accounts,
    }
    logger.info("funding_reconcile_complete", **result)
    return result
