"""Unit tests for the Radar static quality gate.

Each test starts from an all-passing synthetic asset and flips one field to
the failing value, so an empty result isolates exactly one rule.
"""

from datetime import date, timedelta

from app.models.asset import Asset
from app.services.radar_job.quality_gate import StaticQualityGate


def _asset(**overrides) -> Asset:
    """An asset that passes every gate rule unless a field is overridden."""
    defaults = dict(
        symbol="GOOD",
        name="Good Co",
        exchange="NASDAQ",
        tradeable=True,
        asset_type="stock",
        market_cap=10_000_000_000,
        ipo_date=date(2000, 1, 1),
        sector="Technology",
        industry="Software",
        country="US",
    )
    defaults.update(overrides)
    return Asset(**defaults)


def _symbols(assets: list[Asset]) -> set[str]:
    return {a.symbol for a in assets}


class TestPassingAsset:
    def test_all_rules_pass_included(self):
        good = _asset()
        assert StaticQualityGate.filter([good]) == [good]

    def test_allowlisted_etf_included(self):
        spy = _asset(symbol="SPY", asset_type="etf", exchange="ARCA")
        assert StaticQualityGate.filter([spy]) == [spy]

    def test_allowlisted_etf_match_is_case_insensitive(self):
        spy = _asset(symbol="spy", asset_type="etf", exchange="ARCA")
        assert StaticQualityGate.filter([spy]) == [spy]

    def test_null_ipo_date_is_not_treated_as_recent(self):
        # A data gap on an otherwise-qualifying large cap is kept; only a
        # known recent IPO date is filtered.
        asset = _asset(ipo_date=None)
        assert StaticQualityGate.filter([asset]) == [asset]


class TestMarketCap:
    def test_below_floor_excluded(self):
        asset = _asset(market_cap=1_999_999_999)
        assert StaticQualityGate.filter([asset]) == []

    def test_null_excluded(self):
        asset = _asset(market_cap=None)
        assert StaticQualityGate.filter([asset]) == []

    def test_at_floor_included(self):
        asset = _asset(market_cap=2_000_000_000)
        assert StaticQualityGate.filter([asset]) == [asset]


class TestIpoAge:
    def test_recent_ipo_excluded(self):
        asset = _asset(ipo_date=date.today() - timedelta(days=100))
        assert StaticQualityGate.filter([asset]) == []

    def test_old_ipo_included(self):
        asset = _asset(ipo_date=date.today() - timedelta(days=400))
        assert StaticQualityGate.filter([asset]) == [asset]


class TestExchange:
    def test_otc_excluded(self):
        asset = _asset(exchange="OTC")
        assert StaticQualityGate.filter([asset]) == []

    def test_null_exchange_excluded(self):
        asset = _asset(exchange=None)
        assert StaticQualityGate.filter([asset]) == []

    def test_arca_and_bats_allowed(self):
        arca = _asset(symbol="A1", exchange="ARCA")
        bats = _asset(symbol="B1", exchange="BATS")
        assert _symbols(StaticQualityGate.filter([arca, bats])) == {"A1", "B1"}


class TestAssetType:
    def test_fund_excluded(self):
        asset = _asset(asset_type="fund")
        assert StaticQualityGate.filter([asset]) == []

    def test_null_excluded(self):
        asset = _asset(asset_type=None)
        assert StaticQualityGate.filter([asset]) == []


class TestEtfAllowlist:
    def test_etf_not_in_allowlist_excluded(self):
        asset = _asset(symbol="ARKK", asset_type="etf", exchange="ARCA")
        assert StaticQualityGate.filter([asset]) == []


class TestExcludedSymbols:
    def test_leveraged_symbol_excluded_even_if_otherwise_eligible(self):
        # asset_type forced to "stock" so only the deny-list can reject it.
        asset = _asset(symbol="TQQQ", asset_type="stock")
        assert StaticQualityGate.filter([asset]) == []


class TestExcludedIndustries:
    def test_excluded_industry_dropped(self):
        asset = _asset(industry="Cannabis")
        assert StaticQualityGate.filter([asset]) == []


class TestChineseADR:
    def test_country_cn_excluded(self):
        asset = _asset(country="CN")
        assert StaticQualityGate.filter([asset]) == []

    def test_null_country_not_excluded(self):
        asset = _asset(country=None)
        assert StaticQualityGate.filter([asset]) == [asset]


class TestTradeable:
    def test_untradeable_excluded(self):
        asset = _asset(tradeable=False)
        assert StaticQualityGate.filter([asset]) == []


class TestMixedUniverse:
    def test_keeps_only_eligible_and_preserves_order(self):
        good_a = _asset(symbol="AAA")
        penny = _asset(symbol="PENNY", market_cap=100_000_000)
        good_b = _asset(symbol="BBB")
        otc = _asset(symbol="OTCX", exchange="OTC")
        spy = _asset(symbol="SPY", asset_type="etf", exchange="ARCA")

        result = StaticQualityGate.filter([good_a, penny, good_b, otc, spy])

        assert [a.symbol for a in result] == ["AAA", "BBB", "SPY"]

    def test_empty_input_returns_empty(self):
        assert StaticQualityGate.filter([]) == []
