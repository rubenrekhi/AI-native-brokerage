"""Unit tests for the FMP enrichment pass of the daily asset sync."""

import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions import (
    MarketDataError,
    MarketDataUnavailableError,
    MarketDataUpstreamError,
)
from app.tasks import sync_assets as sync_assets_mod
from app.tasks.sync_assets import (
    ENRICHMENT_BATCH_LIMIT,
    ENRICHMENT_COLD_START_BATCH_LIMIT,
    ENRICHMENT_COLD_START_EXIT_THRESHOLD,
    ENRICHMENT_CONCURRENCY,
    ENRICHMENT_REQUESTS_PER_MINUTE,
    ENRICHMENT_STALE_DAYS,
    _enrich_assets,
    sync_assets,
)

FULL_PROFILE = {
    "companyName": "Apple Inc.",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "marketCap": 3_000_000_000_000,
    "ipoDate": "1980-12-12",
    "country": "US",
    "isEtf": False,
    "isFund": False,
}


def _install_enrichment_session(monkeypatch) -> MagicMock:
    """Patch ``async_session`` with a fake CM and stub the repository writes
    so ``_enrich_assets`` runs without a real DB. Returns the session mock."""
    session = MagicMock()
    session.commit = AsyncMock()

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(sync_assets_mod, "async_session", lambda: _SessionCM())
    monkeypatch.setattr(
        sync_assets_mod.AssetRepository,
        "count_enriched_assets",
        AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
    )
    return session


class TestEnrichAssetsMapping:
    async def test_profile_populates_all_new_columns(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["AAPL"]),
        )
        captured: list[dict] = []

        async def _apply(session, rows):
            captured.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", _apply
        )
        marked: list[str] = []

        async def _mark(session, symbols):
            marked.extend(symbols)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", _mark
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock(return_value=FULL_PROFILE)

        counts = await _enrich_assets(fmp)

        assert captured == [
            {
                "symbol": "AAPL",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "market_cap": 3_000_000_000_000,
                "ipo_date": date(1980, 12, 12),
                "asset_type": "stock",
                "country": "US",
            }
        ]
        assert counts == {"enriched": 1, "no_data": 0, "failed": 0}
        # No symbols hit the no-data path, so nothing gets marked.
        assert marked == []

    async def test_etf_and_fund_asset_types(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["SPY", "VTSAX"]),
        )
        captured: list[dict] = []

        async def _apply(session, rows):
            captured.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", _apply
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", AsyncMock()
        )

        profiles = {
            "SPY": {"isEtf": True, "isFund": False},
            "VTSAX": {"isEtf": False, "isFund": True},
        }
        fmp = MagicMock()
        fmp.profile = AsyncMock(side_effect=lambda s: profiles[s])

        await _enrich_assets(fmp)

        by_symbol = {r["symbol"]: r["asset_type"] for r in captured}
        assert by_symbol == {"SPY": "etf", "VTSAX": "fund"}

    async def test_blank_and_missing_fields_become_none(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["XYZ"]),
        )
        captured: list[dict] = []

        async def _apply(session, rows):
            captured.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", _apply
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", AsyncMock()
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock(
            return_value={
                "sector": "",
                "industry": "   ",
                "marketCap": None,
                "ipoDate": "",
                "country": None,
            }
        )

        await _enrich_assets(fmp)

        row = captured[0]
        assert row["sector"] is None
        assert row["industry"] is None
        assert row["market_cap"] is None
        assert row["ipo_date"] is None
        assert row["country"] is None
        assert row["asset_type"] == "stock"


class TestEnrichAssetsBatching:
    async def test_respects_cap_and_stagger(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        list_mock = AsyncMock(return_value=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            list_mock,
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock()

        await _enrich_assets(fmp)

        assert list_mock.await_args.kwargs == {
            "limit": ENRICHMENT_BATCH_LIMIT,
            "stale_days": ENRICHMENT_STALE_DAYS,
        }
        assert ENRICHMENT_BATCH_LIMIT == 500
        assert ENRICHMENT_STALE_DAYS == 30

    async def test_empty_batch_short_circuits(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=[]),
        )
        apply_mock = AsyncMock()
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", apply_mock
        )
        fmp = MagicMock()
        fmp.profile = AsyncMock()

        counts = await _enrich_assets(fmp)

        assert counts == {"enriched": 0, "no_data": 0, "failed": 0}
        fmp.profile.assert_not_awaited()
        apply_mock.assert_not_awaited()

    async def test_concurrency_capped(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        symbols = [f"S{i:02d}" for i in range(25)]
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=symbols),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", AsyncMock()
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", AsyncMock()
        )
        monkeypatch.setattr(
            sync_assets_mod._PerMinuteRateLimiter,
            "acquire",
            AsyncMock(),
        )

        state = {"active": 0, "peak": 0}

        async def _profile(symbol):
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
            await asyncio.sleep(0.01)
            state["active"] -= 1
            return {"sector": "Tech"}

        fmp = MagicMock()
        fmp.profile = AsyncMock(side_effect=_profile)

        await _enrich_assets(fmp)

        assert state["peak"] <= ENRICHMENT_CONCURRENCY
        # With 25 symbols and a real await, the cap should actually be hit.
        assert state["peak"] == ENRICHMENT_CONCURRENCY

    async def test_cold_start_uses_smaller_batch_limit(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        list_mock = AsyncMock(return_value=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=0),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            list_mock,
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock()

        await _enrich_assets(fmp)

        assert list_mock.await_args.kwargs == {
            "limit": ENRICHMENT_COLD_START_BATCH_LIMIT,
            "stale_days": ENRICHMENT_STALE_DAYS,
        }

    async def test_rate_limiter_paces_request_starts(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["AAPL", "TSLA", "MSFT"]),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", AsyncMock()
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", AsyncMock()
        )

        sleeps: list[float] = []

        async def _fake_sleep(delay: float):
            sleeps.append(delay)

        monkeypatch.setattr(sync_assets_mod.asyncio, "sleep", _fake_sleep)
        ticks = iter([0.0, 0.0, 0.2, 0.2, 0.8, 0.8])
        monkeypatch.setattr(sync_assets_mod, "monotonic", lambda: next(ticks))

        fmp = MagicMock()
        fmp.profile = AsyncMock(return_value=FULL_PROFILE)

        await _enrich_assets(fmp)

        interval = 60 / ENRICHMENT_REQUESTS_PER_MINUTE
        assert sleeps == pytest.approx([interval, (2 * interval) - 0.2])

    async def test_stays_in_cold_start_until_threshold(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        list_mock = AsyncMock(return_value=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD - 1),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            list_mock,
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock()

        await _enrich_assets(fmp)

        assert list_mock.await_args.kwargs == {
            "limit": ENRICHMENT_COLD_START_BATCH_LIMIT,
            "stale_days": ENRICHMENT_STALE_DAYS,
        }


class TestEnrichAssetsErrorPaths:
    async def test_402_marks_enriched_without_writing_data(self, monkeypatch):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["AAPL", "OBSCURE"]),
        )
        applied: list[dict] = []
        marked: list[str] = []

        async def _apply(session, rows):
            applied.extend(rows)

        async def _mark(session, symbols):
            marked.extend(symbols)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", _apply
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", _mark
        )

        async def _profile(symbol):
            if symbol == "OBSCURE":
                raise MarketDataError("not in tier", symbol="OBSCURE")
            return FULL_PROFILE

        fmp = MagicMock()
        fmp.profile = AsyncMock(side_effect=_profile)

        counts = await _enrich_assets(fmp)

        assert [r["symbol"] for r in applied] == ["AAPL"]
        assert marked == ["OBSCURE"]
        assert counts == {"enriched": 1, "no_data": 1, "failed": 0}

    @pytest.mark.parametrize(
        "exc",
        [MarketDataUnavailableError(), MarketDataUpstreamError(status_code=500)],
    )
    async def test_transient_error_left_for_next_run(self, monkeypatch, exc):
        _install_enrichment_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "count_enriched_assets",
            AsyncMock(return_value=ENRICHMENT_COLD_START_EXIT_THRESHOLD),
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "list_symbols_needing_enrichment",
            AsyncMock(return_value=["AAPL"]),
        )
        applied: list[dict] = []
        marked: list[str] = []

        async def _apply(session, rows):
            applied.extend(rows)

        async def _mark(session, symbols):
            marked.extend(symbols)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "apply_enrichment", _apply
        )
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "mark_enriched", _mark
        )

        fmp = MagicMock()
        fmp.profile = AsyncMock(side_effect=exc)

        counts = await _enrich_assets(fmp)

        # Transient failures must NOT stamp enriched_at — the symbol stays
        # eligible for the next run.
        assert counts == {"enriched": 0, "no_data": 0, "failed": 1}
        assert applied == []
        assert marked == []


class TestSyncAssetsEnrichmentWiring:
    async def test_enrichment_runs_and_lands_in_summary(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                {
                    "id": "alp_aapl",
                    "symbol": "AAPL",
                    "name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    "fractionable": True,
                }
            ]
        )
        _install_full_sync_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )
        enrich = AsyncMock(return_value={"enriched": 3, "no_data": 1, "failed": 0})
        monkeypatch.setattr(sync_assets_mod, "_enrich_assets", enrich)

        fmp = MagicMock()
        summary = await sync_assets({"alpaca": broker, "fmp": fmp})

        enrich.assert_awaited_once_with(fmp)
        assert summary["enrichment"] == {"enriched": 3, "no_data": 1, "failed": 0}

    async def test_enrichment_skipped_without_fmp(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                {
                    "id": "alp_aapl",
                    "symbol": "AAPL",
                    "name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    "fractionable": True,
                }
            ]
        )
        _install_full_sync_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )
        enrich = AsyncMock()
        monkeypatch.setattr(sync_assets_mod, "_enrich_assets", enrich)

        summary = await sync_assets({"alpaca": broker})

        enrich.assert_not_awaited()
        assert "enrichment" not in summary

    async def test_enrichment_failure_does_not_break_sync(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                {
                    "id": "alp_aapl",
                    "symbol": "AAPL",
                    "name": "Apple Inc",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    "fractionable": True,
                }
            ]
        )
        _install_full_sync_session(monkeypatch)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )
        monkeypatch.setattr(
            sync_assets_mod,
            "_enrich_assets",
            AsyncMock(side_effect=RuntimeError("fmp exploded")),
        )
        scope = MagicMock()
        scope.__enter__ = MagicMock(return_value=scope)
        scope.__exit__ = MagicMock(return_value=None)
        monkeypatch.setattr(
            sync_assets_mod.sentry_sdk, "new_scope", MagicMock(return_value=scope)
        )
        monkeypatch.setattr(
            sync_assets_mod.sentry_sdk, "capture_exception", MagicMock()
        )

        fmp = MagicMock()
        summary = await sync_assets({"alpaca": broker, "fmp": fmp})

        # The catalog sync still reports its counts; enrichment failure is
        # swallowed (logged + captured) and omitted from the summary.
        assert summary["total"] == 1
        assert "enrichment" not in summary
        tag_calls = {call.args for call in scope.set_tag.call_args_list}
        assert ("failure_stage", "fmp_enrichment") in tag_calls


def _install_full_sync_session(monkeypatch) -> None:
    """Fake ``async_session`` for the upsert path of the full task."""
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.all = MagicMock(return_value=[])
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    begin_cm = MagicMock()
    begin_cm.__aenter__ = AsyncMock(return_value=session)
    begin_cm.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_cm)

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(sync_assets_mod, "async_session", lambda: _SessionCM())
