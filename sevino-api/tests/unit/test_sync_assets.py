"""Unit tests for the daily asset sync task."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.alpaca_broker import (
    AlpacaBrokerError,
    AlpacaBrokerUnavailableError,
)
from app.tasks import sync_assets as sync_assets_mod
from app.tasks.sync_assets import sync_assets


def _alpaca_asset(
    *,
    symbol: str,
    name: str,
    exchange: str = "NASDAQ",
    asset_id: str | None = None,
    fractionable: bool = True,
) -> dict:
    return {
        "id": asset_id or f"alp_{symbol.lower()}",
        "symbol": symbol,
        "name": name,
        "exchange": exchange,
        "status": "active",
        "tradable": True,
        "fractionable": fractionable,
    }


def _install_fake_session(
    monkeypatch: pytest.MonkeyPatch, existing: list[tuple[str, bool]]
):
    """Replace ``async_session`` with a fake that yields a MagicMock session
    whose ``.execute`` returns ``existing`` for the pre-sync SELECT and a
    no-op for the upsert. Returns the session mock for assertions."""

    session = MagicMock()
    execute_result = MagicMock()
    execute_result.all = MagicMock(return_value=list(existing))
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    session.flush = AsyncMock()

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(sync_assets_mod, "async_session", lambda: _SessionCM())
    return session


class TestSyncAssetsUpsert:
    async def test_passes_fmp_logo_url_per_symbol(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                _alpaca_asset(symbol="AAPL", name="Apple Inc"),
                _alpaca_asset(symbol="TSLA", name="Tesla Inc"),
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        bulk_upsert = AsyncMock()
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", bulk_upsert
        )

        await sync_assets({"alpaca": broker})

        bulk_upsert.assert_awaited_once()
        _, rows = bulk_upsert.await_args.args
        by_symbol = {r["symbol"]: r for r in rows}
        assert by_symbol["AAPL"]["logo_url"] == (
            "https://financialmodelingprep.com/image-stock/AAPL.png"
        )
        assert by_symbol["TSLA"]["logo_url"] == (
            "https://financialmodelingprep.com/image-stock/TSLA.png"
        )

    async def test_populates_full_asset_row(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                _alpaca_asset(
                    symbol="AAPL", name="Apple Inc", exchange="NASDAQ",
                    asset_id="alp_aapl_id",
                ),
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        captured_rows: list[dict] = []

        async def _capture(session, rows):
            captured_rows.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", _capture
        )

        await sync_assets({"alpaca": broker})

        assert captured_rows == [
            {
                "symbol": "AAPL",
                "name": "Apple Inc",
                "exchange": "NASDAQ",
                "tradeable": True,
                "fractionable": True,
                "logo_url": (
                    "https://financialmodelingprep.com/image-stock/AAPL.png"
                ),
                "alpaca_asset_id": "alp_aapl_id",
            }
        ]

    async def test_calls_alpaca_with_active_us_equity_filter(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(return_value=[])
        _install_fake_session(monkeypatch, existing=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )

        await sync_assets({"alpaca": broker})

        broker.list_assets.assert_awaited_once_with(
            status="active", asset_class="us_equity"
        )


class TestSyncAssetsFractionable:
    async def test_captures_fractionable_true(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                _alpaca_asset(symbol="AAPL", name="Apple Inc", fractionable=True),
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        captured_rows: list[dict] = []

        async def _capture(session, rows):
            captured_rows.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", _capture
        )

        await sync_assets({"alpaca": broker})

        assert captured_rows[0]["fractionable"] is True

    async def test_captures_fractionable_false(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                _alpaca_asset(
                    symbol="ILLQ", name="Illiquid Co", fractionable=False
                ),
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        captured_rows: list[dict] = []

        async def _capture(session, rows):
            captured_rows.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", _capture
        )

        await sync_assets({"alpaca": broker})

        assert captured_rows[0]["fractionable"] is False

    async def test_defaults_fractionable_true_when_field_missing(
        self, monkeypatch
    ):
        # Defensive: Alpaca has always included the field, but a future
        # response shape change shouldn't crash the sync — match the column
        # default so existing "let Alpaca decide" behavior is preserved.
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                {
                    "id": "alp_xyz",
                    "symbol": "XYZ",
                    "name": "Xyz Corp",
                    "exchange": "NASDAQ",
                    "status": "active",
                    "tradable": True,
                    # fractionable intentionally omitted
                },
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        captured_rows: list[dict] = []

        async def _capture(session, rows):
            captured_rows.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", _capture
        )

        await sync_assets({"alpaca": broker})

        assert captured_rows[0]["fractionable"] is True


class TestSyncAssetsSummary:
    async def test_reports_new_updated_and_deactivated_counts(
        self, monkeypatch
    ):
        # Existing: AAPL (tradeable), TSLA (tradeable), OLDCO (tradeable, no
        # longer in feed → should be counted as deactivated), DEAD (already
        # untradeable — must NOT be counted as deactivated again).
        existing = [
            ("AAPL", True),
            ("TSLA", True),
            ("OLDCO", True),
            ("DEAD", False),
        ]
        # Feed: AAPL (updated), TSLA (updated), MSFT (new)
        feed = [
            _alpaca_asset(symbol="AAPL", name="Apple Inc"),
            _alpaca_asset(symbol="TSLA", name="Tesla Inc"),
            _alpaca_asset(symbol="MSFT", name="Microsoft Corp"),
        ]
        broker = MagicMock()
        broker.list_assets = AsyncMock(return_value=feed)
        _install_fake_session(monkeypatch, existing=existing)
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )

        summary = await sync_assets({"alpaca": broker})

        assert summary == {
            "total": 3,
            "new": 1,
            "updated": 2,
            "deactivated": 1,
        }

    async def test_logs_assets_synced_event(self, monkeypatch):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[_alpaca_asset(symbol="AAPL", name="Apple Inc")]
        )
        _install_fake_session(monkeypatch, existing=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )
        info = MagicMock()
        monkeypatch.setattr(sync_assets_mod.logger, "info", info)

        await sync_assets({"alpaca": broker})

        info.assert_called_once()
        event, kwargs = info.call_args.args[0], info.call_args.kwargs
        assert event == "assets_synced"
        assert kwargs == {"total": 1, "new": 1, "updated": 0, "deactivated": 0}


class TestSyncAssetsErrorHandling:
    async def test_alpaca_unavailable_logs_warning_and_returns(
        self, monkeypatch
    ):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            side_effect=AlpacaBrokerUnavailableError("timeout")
        )
        # If the task reached the DB, this would explode — we assert it
        # never gets past the Alpaca call on the unavailable path.
        def _no_db():
            raise AssertionError("async_session must not be called")

        monkeypatch.setattr(sync_assets_mod, "async_session", _no_db)
        warning = MagicMock()
        monkeypatch.setattr(sync_assets_mod.logger, "warning", warning)

        result = await sync_assets({"alpaca": broker})

        assert result == {"status": "skipped", "reason": "alpaca_unavailable"}
        warning.assert_called_once()
        assert warning.call_args.args[0] == "assets_sync_alpaca_unavailable"

    async def test_unexpected_alpaca_error_captures_and_reraises(
        self, monkeypatch
    ):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            side_effect=AlpacaBrokerError(500, "boom")
        )
        # Guard: we expect the error path to short-circuit before any DB work.
        def _no_db():
            raise AssertionError("async_session must not be called")

        monkeypatch.setattr(sync_assets_mod, "async_session", _no_db)
        scope = MagicMock()
        scope.__enter__ = MagicMock(return_value=scope)
        scope.__exit__ = MagicMock(return_value=None)
        monkeypatch.setattr(
            sync_assets_mod.sentry_sdk, "new_scope", MagicMock(return_value=scope)
        )
        capture = MagicMock()
        monkeypatch.setattr(sync_assets_mod.sentry_sdk, "capture_exception", capture)

        with pytest.raises(AlpacaBrokerError):
            await sync_assets({"alpaca": broker})

        capture.assert_called_once()
        # Scope must be tagged so ops can filter sync_assets failures.
        tag_calls = {call.args for call in scope.set_tag.call_args_list}
        assert ("arq_task", "sync_assets") in tag_calls
        assert ("failure_stage", "alpaca_list_assets") in tag_calls

    async def test_empty_alpaca_feed_skips_db_work(self, monkeypatch):
        # An empty active-us-equity response is almost certainly an Alpaca
        # glitch, not a real "nothing tradeable" state — hitting bulk_upsert
        # with it would skip the soft-deactivate pass and mislead ops.
        broker = MagicMock()
        broker.list_assets = AsyncMock(return_value=[])

        def _no_db():
            raise AssertionError("async_session must not be called")

        monkeypatch.setattr(sync_assets_mod, "async_session", _no_db)
        warning = MagicMock()
        monkeypatch.setattr(sync_assets_mod.logger, "warning", warning)

        result = await sync_assets({"alpaca": broker})

        assert result == {"status": "skipped", "reason": "empty_feed"}
        warning.assert_called_once()
        assert warning.call_args.args[0] == "assets_sync_empty_feed"

    async def test_malformed_rows_are_skipped_not_fatal(self, monkeypatch):
        # One poisoned entry in a ~12k batch must not abort the whole sync.
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[
                _alpaca_asset(symbol="AAPL", name="Apple Inc"),
                {"id": "alp_bad", "exchange": "NASDAQ"},  # missing symbol+name
                _alpaca_asset(symbol="TSLA", name="Tesla Inc"),
            ]
        )
        _install_fake_session(monkeypatch, existing=[])
        captured_rows: list[dict] = []

        async def _capture(session, rows):
            captured_rows.extend(rows)

        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", _capture
        )
        warning = MagicMock()
        monkeypatch.setattr(sync_assets_mod.logger, "warning", warning)

        summary = await sync_assets({"alpaca": broker})

        assert {r["symbol"] for r in captured_rows} == {"AAPL", "TSLA"}
        assert summary["total"] == 2
        warning.assert_called_once()
        event, kwargs = (
            warning.call_args.args[0],
            warning.call_args.kwargs,
        )
        assert event == "assets_sync_malformed_rows_skipped"
        assert kwargs == {"count": 1}

    async def test_db_upsert_failure_captures_with_scope_and_reraises(
        self, monkeypatch
    ):
        broker = MagicMock()
        broker.list_assets = AsyncMock(
            return_value=[_alpaca_asset(symbol="AAPL", name="Apple Inc")]
        )
        _install_fake_session(monkeypatch, existing=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository,
            "bulk_upsert",
            AsyncMock(side_effect=RuntimeError("db exploded")),
        )
        scope = MagicMock()
        scope.__enter__ = MagicMock(return_value=scope)
        scope.__exit__ = MagicMock(return_value=None)
        monkeypatch.setattr(
            sync_assets_mod.sentry_sdk, "new_scope", MagicMock(return_value=scope)
        )
        capture = MagicMock()
        monkeypatch.setattr(sync_assets_mod.sentry_sdk, "capture_exception", capture)

        with pytest.raises(RuntimeError):
            await sync_assets({"alpaca": broker})

        capture.assert_called_once()
        tag_calls = {call.args for call in scope.set_tag.call_args_list}
        assert ("arq_task", "sync_assets") in tag_calls
        assert ("failure_stage", "db_upsert") in tag_calls


class TestManualTrigger:
    async def test_builds_and_closes_broker_when_ctx_missing_alpaca(
        self, monkeypatch
    ):
        """Invoked outside ARQ (`uv run python -c ...`), ctx has no alpaca
        — the task must construct and dispose its own broker."""
        fake_broker = MagicMock()
        fake_broker.list_assets = AsyncMock(return_value=[])
        fake_broker.close = AsyncMock()
        factory = MagicMock(return_value=fake_broker)
        monkeypatch.setattr(sync_assets_mod, "AlpacaBrokerService", factory)
        _install_fake_session(monkeypatch, existing=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )

        await sync_assets({})

        factory.assert_called_once()
        fake_broker.close.assert_awaited_once()

    async def test_provided_broker_is_not_closed(self, monkeypatch):
        """When ARQ supplies the shared broker via ctx, the task must not
        close it — the worker owns its lifecycle."""
        broker = MagicMock()
        broker.list_assets = AsyncMock(return_value=[])
        broker.close = AsyncMock()
        _install_fake_session(monkeypatch, existing=[])
        monkeypatch.setattr(
            sync_assets_mod.AssetRepository, "bulk_upsert", AsyncMock()
        )

        await sync_assets({"alpaca": broker})

        broker.close.assert_not_awaited()
