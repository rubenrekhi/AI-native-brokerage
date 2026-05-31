from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.brokerage import (
    DividendListResponse,
    DividendResponse,
    OrderListResponse,
    OrderResponse,
)
from app.services.digest.generators import (
    DividendsGenerator,
    PendingOrdersGenerator,
    RadarRefreshGenerator,
)
import app.services.digest.generators.dividends as dividends_module
import app.services.digest.generators.pending_orders as pending_orders_module
import app.services.digest.generators.radar_refresh as radar_refresh_module
from app.services.digest.generators.radar_refresh import RADAR_REFRESH_MAGNITUDE
from app.services.digest.types import DigestContext, MarketState


def _ctx(*, now: datetime | None = None) -> DigestContext:
    return DigestContext(
        user_id=uuid4(),
        portfolio_snapshot=None,
        holdings=[],
        financial_profile=None,
        market_state=MarketState(
            as_of=now or datetime(2026, 6, 2, 13, tzinfo=timezone.utc),
            session="pre",
        ),
    )


class TestDividendsGenerator:
    async def test_returns_empty_without_recent_payments(self, monkeypatch):
        monkeypatch.setattr(
            dividends_module.BrokerageService,
            "list_dividends",
            AsyncMock(
                return_value=DividendListResponse(
                    dividends=[
                        DividendResponse(
                            id="div_old",
                            symbol="AAPL",
                            net_amount="1.25",
                            status="executed",
                            created_at="2026-05-29T13:00:00Z",
                        )
                    ]
                )
            ),
        )

        result = await DividendsGenerator().generate(
            _ctx(), AsyncMock(), AsyncMock()
        )

        assert result == []

    async def test_builds_card_and_scores_total_amount(self, monkeypatch):
        monkeypatch.setattr(
            dividends_module.BrokerageService,
            "list_dividends",
            AsyncMock(
                return_value=DividendListResponse(
                    dividends=[
                        DividendResponse(
                            id="div_a",
                            symbol="aapl",
                            net_amount="1.25",
                            status="executed",
                            created_at="2026-06-02T12:00:00Z",
                        ),
                        DividendResponse(
                            id="div_b",
                            symbol="MSFT",
                            net_amount="2.75",
                            status="executed",
                            created_at="2026-06-02T12:30:00Z",
                        ),
                    ]
                )
            ),
        )

        candidates = await DividendsGenerator().generate(
            _ctx(), AsyncMock(), AsyncMock()
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.event_type == "dividends"
        assert candidate.magnitude_score == 4.0
        assert candidate.related_symbols == ["AAPL", "MSFT"]
        assert candidate.card.total_amount == Decimal("4.00")
        assert candidate.card.period_label == "since yesterday"

    async def test_multi_day_window_uses_this_week_label(self, monkeypatch):
        monkeypatch.setattr(
            dividends_module.BrokerageService,
            "list_dividends",
            AsyncMock(
                return_value=DividendListResponse(
                    dividends=[
                        DividendResponse(
                            id="div_a",
                            symbol="AAPL",
                            net_amount="1.00",
                            status="executed",
                            created_at="2026-06-01T12:00:00Z",
                        )
                    ]
                )
            ),
        )

        candidates = await DividendsGenerator(lookback_days=3).generate(
            _ctx(), AsyncMock(), AsyncMock()
        )

        assert candidates[0].card.period_label == "this week"


class TestPendingOrdersGenerator:
    async def test_returns_empty_without_order_activity(self, monkeypatch):
        list_orders = AsyncMock(return_value=OrderListResponse(orders=[]))
        monkeypatch.setattr(
            pending_orders_module.BrokerageService, "list_orders", list_orders
        )

        result = await PendingOrdersGenerator().generate(
            _ctx(), AsyncMock(), AsyncMock()
        )

        assert result == []

    async def test_buckets_recent_filled_and_recurring_orders(self, monkeypatch):
        orders = [
            OrderResponse(
                id="ord_regular",
                client_order_id="manual-1",
                symbol="TSLA",
                side="buy",
                qty="2",
                notional="500.00",
                filled_qty="2",
                status="filled",
                filled_at="2026-06-01T12:30:00Z",
            ),
            OrderResponse(
                id="ord_recurring",
                client_order_id="recurring-weekly-1",
                symbol="VOO",
                side="buy",
                notional="100.00",
                status="filled",
                filled_at="2026-06-01T12:45:00Z",
            ),
            OrderResponse(
                id="ord_skipped",
                client_order_id="dca_weekly_2",
                symbol="QQQ",
                side="buy",
                notional="25.00",
                status="rejected",
                failed_at="2026-06-01T12:50:00Z",
            ),
            OrderResponse(
                id="ord_old",
                client_order_id="manual-old",
                symbol="AAPL",
                side="buy",
                notional="1000.00",
                status="filled",
                filled_at="2026-05-29T19:59:00Z",
            ),
        ]
        list_orders = AsyncMock(return_value=OrderListResponse(orders=orders))
        monkeypatch.setattr(
            pending_orders_module.BrokerageService, "list_orders", list_orders
        )
        ctx = _ctx(now=datetime(2026, 6, 1, 13, tzinfo=timezone.utc))

        candidates = await PendingOrdersGenerator().generate(
            ctx, AsyncMock(), AsyncMock()
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.event_type == "pending_order_activity"
        assert candidate.related_symbols == ["QQQ", "TSLA", "VOO"]
        assert candidate.magnitude_score == 600.0
        card = candidate.card
        assert [item.symbol for item in card.filled] == ["TSLA"]
        assert [item.symbol for item in card.recurring_executed] == ["VOO"]
        assert [item.symbol for item in card.recurring_skipped] == ["QQQ"]
        assert card.card_context["activity_count"] == 3
        list_orders.assert_awaited_once()
        assert list_orders.await_args.kwargs["after"] == (
            "2026-05-29T20:00:00+00:00"
        )

    async def test_includes_partially_filled_orders(self, monkeypatch):
        orders = [
            OrderResponse(
                id="ord_partial",
                client_order_id="manual-partial",
                symbol="NVDA",
                side="buy",
                qty="3",
                filled_qty="1",
                filled_avg_price="150.00",
                status="partially_filled",
                submitted_at="2026-06-01T12:30:00Z",
            )
        ]
        monkeypatch.setattr(
            pending_orders_module.BrokerageService,
            "list_orders",
            AsyncMock(return_value=OrderListResponse(orders=orders)),
        )
        ctx = _ctx(now=datetime(2026, 6, 1, 13, tzinfo=timezone.utc))

        candidates = await PendingOrdersGenerator().generate(
            ctx, AsyncMock(), AsyncMock()
        )

        assert len(candidates) == 1
        assert [item.symbol for item in candidates[0].card.filled] == ["NVDA"]
        assert candidates[0].card.filled[0].qty == Decimal("1")
        assert candidates[0].card.filled[0].notional == Decimal("150.00")


class TestRadarRefreshGenerator:
    async def test_returns_empty_when_not_refresh_day(self, monkeypatch):
        profile = SimpleNamespace(
            next_radar_refresh_at=datetime(2026, 6, 3, 13, tzinfo=timezone.utc)
        )
        monkeypatch.setattr(
            radar_refresh_module.UserProfileRepository,
            "get_by_id",
            AsyncMock(return_value=profile),
        )
        monkeypatch.setattr(
            radar_refresh_module.RadarItemRepository,
            "list_for_user",
            AsyncMock(return_value=[]),
        )

        result = await RadarRefreshGenerator().generate(
            _ctx(now=datetime(2026, 6, 2, 13, tzinfo=timezone.utc)),
            AsyncMock(),
            AsyncMock(),
        )

        assert result == []

    async def test_builds_fixed_weight_refresh_card(self, monkeypatch):
        profile = SimpleNamespace(
            next_radar_refresh_at=datetime(2026, 6, 2, 13, tzinfo=timezone.utc)
        )
        monkeypatch.setattr(
            radar_refresh_module.UserProfileRepository,
            "get_by_id",
            AsyncMock(return_value=profile),
        )
        monkeypatch.setattr(
            radar_refresh_module.RadarItemRepository,
            "list_for_user",
            AsyncMock(
                return_value=[
                    SimpleNamespace(
                        symbol="AAPL",
                        source="ai_generated",
                        created_at=datetime(
                            2026, 6, 2, 12, tzinfo=timezone.utc
                        ),
                    ),
                    SimpleNamespace(
                        symbol="MSFT",
                        source="ai_generated",
                        created_at=datetime(
                            2026, 6, 2, 12, 30, tzinfo=timezone.utc
                        ),
                    ),
                    SimpleNamespace(
                        symbol="VOO",
                        source="ai_generated",
                        created_at=datetime(
                            2026, 6, 1, 12, tzinfo=timezone.utc
                        ),
                    ),
                    SimpleNamespace(
                        symbol="TSLA",
                        source="user_added",
                        created_at=datetime(
                            2026, 6, 2, 12, tzinfo=timezone.utc
                        ),
                    ),
                ]
            ),
        )

        candidates = await RadarRefreshGenerator().generate(
            _ctx(now=datetime(2026, 6, 2, 13, tzinfo=timezone.utc)),
            AsyncMock(),
            AsyncMock(),
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.event_type == "radar_refresh"
        assert candidate.magnitude_score == RADAR_REFRESH_MAGNITUDE
        assert candidate.related_symbols == ["AAPL", "MSFT"]
        assert candidate.card.new_count == 2
        assert candidate.card.removed_count == 0
        assert candidate.card.refreshed_at == datetime(
            2026, 6, 2, 12, 30, tzinfo=timezone.utc
        )
        assert candidate.card.card_context["counts_source"] == (
            "radar_items.created_at"
        )
        assert candidate.card.card_context["removed_count_source"] == (
            "not_tracked"
        )

    async def test_returns_empty_when_no_ai_items_created_today(self, monkeypatch):
        profile = SimpleNamespace(
            next_radar_refresh_at=datetime(2026, 6, 9, 13, tzinfo=timezone.utc)
        )
        monkeypatch.setattr(
            radar_refresh_module.UserProfileRepository,
            "get_by_id",
            AsyncMock(return_value=profile),
        )
        monkeypatch.setattr(
            radar_refresh_module.RadarItemRepository,
            "list_for_user",
            AsyncMock(
                return_value=[
                    SimpleNamespace(
                        symbol="AAPL",
                        source="ai_generated",
                        created_at=datetime(
                            2026, 6, 1, 12, tzinfo=timezone.utc
                        ),
                    )
                ]
            ),
        )

        result = await RadarRefreshGenerator().generate(
            _ctx(now=datetime(2026, 6, 2, 13, tzinfo=timezone.utc)),
            AsyncMock(),
            AsyncMock(),
        )

        assert result == []
