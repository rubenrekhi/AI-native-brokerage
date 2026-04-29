"""Unit tests for onboarding derivation functions and payload construction."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.schemas.onboarding import OnboardingSubmitRequest
from app.services.onboarding import (
    INCOME_RANGES,
    LIQUID_NET_WORTH_RANGES,
    NET_WORTH_RANGES,
    build_agreements,
    build_alpaca_payload,
    derive_investment_objective,
    derive_risk_tolerance,
    extract_tax_id_last_4,
    map_employment_status,
    map_experience,
    map_range,
    map_time_horizon,
    validate_completeness,
)


# ---------------------------------------------------------------------------
# derive_risk_tolerance
# ---------------------------------------------------------------------------


class TestDeriveRiskTolerance:

    # sell_everything / sell_some — conservative when low loss, moderate otherwise
    def test_sell_everything_low_loss(self):
        assert derive_risk_tolerance("sell_everything", "0-5%") == "conservative"

    def test_sell_everything_moderate_loss(self):
        assert derive_risk_tolerance("sell_everything", "15-25%") == "moderate"

    def test_sell_some_low_loss(self):
        assert derive_risk_tolerance("sell_some", "5-15%") == "conservative"

    def test_sell_some_high_loss(self):
        assert derive_risk_tolerance("sell_some", "25-40%") == "moderate"

    # hold / not_sure — conservative when low loss, moderate otherwise
    def test_hold_low_loss(self):
        assert derive_risk_tolerance("hold", "0-5%") == "conservative"

    def test_hold_high_loss(self):
        assert derive_risk_tolerance("hold", "40%+") == "moderate"

    def test_not_sure_low_loss(self):
        assert derive_risk_tolerance("not_sure", "5-15%") == "conservative"

    def test_not_sure_moderate_loss(self):
        assert derive_risk_tolerance("not_sure", "15-25%") == "moderate"

    # buy_more — moderate for low/mid, aggressive for high
    def test_buy_more_moderate(self):
        assert derive_risk_tolerance("buy_more", "15-25%") == "moderate"

    def test_buy_more_significant_risk_25_40(self):
        assert derive_risk_tolerance("buy_more", "25-40%") == "significant_risk"

    def test_buy_more_significant_risk_40_plus(self):
        assert derive_risk_tolerance("buy_more", "40%+") == "significant_risk"

    # fallback
    def test_unknown_scenario_returns_moderate(self):
        assert derive_risk_tolerance("unknown", "0-5%") == "moderate"


# ---------------------------------------------------------------------------
# derive_investment_objective
# ---------------------------------------------------------------------------


class TestDeriveInvestmentObjective:

    def test_grow_wealth(self):
        assert derive_investment_objective(["grow_wealth"]) == "growth"

    def test_save_for_goal(self):
        assert derive_investment_objective(["save_for_goal"]) == "growth"

    def test_retirement(self):
        assert derive_investment_objective(["retirement"]) == "growth"

    def test_safety_net(self):
        assert derive_investment_objective(["safety_net"]) == "preserve_wealth"

    def test_make_cash_work(self):
        assert derive_investment_objective(["make_cash_work"]) == "preserve_wealth"

    def test_learn_to_invest(self):
        assert derive_investment_objective(["learn_to_invest"]) == "growth"

    def test_first_match_wins(self):
        assert derive_investment_objective(["learn_to_invest", "grow_wealth"]) == "growth"

    def test_first_match_wins_growth(self):
        assert derive_investment_objective(["grow_wealth", "safety_net"]) == "growth"

    def test_empty_list_fallback(self):
        assert derive_investment_objective([]) == "growth"

    def test_unknown_goal_fallback(self):
        assert derive_investment_objective(["unknown_goal"]) == "growth"


# ---------------------------------------------------------------------------
# map_range — income
# ---------------------------------------------------------------------------


class TestMapRangeIncome:

    def test_under_25k(self):
        assert map_range("Under $25K", INCOME_RANGES) == ("0", "25000")

    def test_25k_49k(self):
        assert map_range("$25K \u2013 $49K", INCOME_RANGES) == ("25000", "50000")

    def test_50k_99k(self):
        assert map_range("$50K \u2013 $99K", INCOME_RANGES) == ("50000", "100000")

    def test_100k_199k(self):
        assert map_range("$100K \u2013 $199K", INCOME_RANGES) == ("100000", "200000")

    def test_200k_499k(self):
        assert map_range("$200K \u2013 $499K", INCOME_RANGES) == ("200000", "500000")

    def test_500k_plus(self):
        assert map_range("$500K+", INCOME_RANGES) == ("500000", "1000000")

    def test_unknown_falls_back_to_first(self):
        result = map_range("invalid", INCOME_RANGES)
        assert result == ("0", "25000")


# ---------------------------------------------------------------------------
# map_range — net worth
# ---------------------------------------------------------------------------


class TestMapRangeNetWorth:

    def test_under_10k(self):
        assert map_range("Under $10K", NET_WORTH_RANGES) == ("0", "10000")

    def test_10k_50k(self):
        assert map_range("$10K \u2013 $50K", NET_WORTH_RANGES) == ("10000", "50000")

    def test_50k_100k(self):
        assert map_range("$50K \u2013 $100K", NET_WORTH_RANGES) == ("50000", "100000")

    def test_100k_250k(self):
        assert map_range("$100K \u2013 $250K", NET_WORTH_RANGES) == ("100000", "250000")

    def test_250k_500k(self):
        assert map_range("$250K \u2013 $500K", NET_WORTH_RANGES) == ("250000", "500000")

    def test_500k_1m(self):
        assert map_range("$500K \u2013 $1M", NET_WORTH_RANGES) == ("500000", "1000000")

    def test_1m_plus(self):
        assert map_range("$1M+", NET_WORTH_RANGES) == ("1000000", "5000000")

    def test_unknown_falls_back_to_first(self):
        result = map_range("invalid", NET_WORTH_RANGES)
        assert result == ("0", "10000")


# ---------------------------------------------------------------------------
# map_range — liquid net worth
# ---------------------------------------------------------------------------


class TestMapRangeLiquidNetWorth:

    def test_under_10k(self):
        assert map_range("Under $10K", LIQUID_NET_WORTH_RANGES) == ("0", "10000")

    def test_10k_25k(self):
        assert map_range("$10K \u2013 $25K", LIQUID_NET_WORTH_RANGES) == ("10000", "25000")

    def test_25k_50k(self):
        assert map_range("$25K \u2013 $50K", LIQUID_NET_WORTH_RANGES) == ("25000", "50000")

    def test_50k_100k(self):
        assert map_range("$50K \u2013 $100K", LIQUID_NET_WORTH_RANGES) == ("50000", "100000")

    def test_100k_250k(self):
        assert map_range("$100K \u2013 $250K", LIQUID_NET_WORTH_RANGES) == ("100000", "250000")

    def test_250k_plus(self):
        assert map_range("$250K+", LIQUID_NET_WORTH_RANGES) == ("250000", "1000000")

    def test_unknown_falls_back_to_first(self):
        result = map_range("invalid", LIQUID_NET_WORTH_RANGES)
        assert result == ("0", "10000")


# ---------------------------------------------------------------------------
# map_time_horizon
# ---------------------------------------------------------------------------


class TestMapTimeHorizon:

    def test_less_than_2_years(self):
        assert map_time_horizon("Less than 2 years") == ("1_to_2_years", "very_important")

    def test_2_5_years(self):
        assert map_time_horizon("2 \u2013 5 years") == ("3_to_5_years", "somewhat_important")

    def test_5_10_years(self):
        assert map_time_horizon("5 \u2013 10 years") == ("6_to_10_years", "does_not_matter")

    def test_10_20_years(self):
        assert map_time_horizon("10 \u2013 20 years") == ("more_than_10_years", "does_not_matter")

    def test_20_plus_years(self):
        assert map_time_horizon("20+ years") == ("more_than_10_years", "does_not_matter")

    def test_unknown_fallback(self):
        assert map_time_horizon("invalid") == ("3_to_5_years", "does_not_matter")


# ---------------------------------------------------------------------------
# map_experience
# ---------------------------------------------------------------------------


class TestMapExperience:

    def test_never_invested(self):
        assert map_experience("never_invested") == "none"

    def test_invested_little(self):
        assert map_experience("invested_little") == "1_to_5_years"

    def test_invest_regularly(self):
        assert map_experience("invest_regularly") == "1_to_5_years"

    def test_actively_manage(self):
        assert map_experience("actively_manage") == "over_5_years"

    def test_advanced_strategies(self):
        assert map_experience("advanced_strategies") == "over_5_years"

    def test_unknown_fallback(self):
        assert map_experience("invalid") == "none"


# ---------------------------------------------------------------------------
# map_employment_status
# ---------------------------------------------------------------------------


class TestMapEmploymentStatus:

    def test_employed(self):
        assert map_employment_status({"employment_status": "employed"}) == "employed"

    def test_self_employed(self):
        assert map_employment_status({"employment_status": "self_employed"}) == "employed"

    def test_unemployed(self):
        assert map_employment_status({"employment_status": "unemployed"}) == "unemployed"

    def test_student(self):
        assert map_employment_status({"employment_status": "student"}) == "student"

    def test_retired(self):
        assert map_employment_status({"employment_status": "retired"}) == "retired"

    def test_case_insensitive(self):
        assert map_employment_status({"employment_status": "Employed"}) == "employed"

    def test_missing_key_fallback(self):
        assert map_employment_status({}) == "employed"


# ---------------------------------------------------------------------------
# build_agreements
# ---------------------------------------------------------------------------


class TestBuildAgreements:

    def test_both_agreements(self):
        result = build_agreements({
            "customer_agreement": True,
            "margin_agreement": True,
            "signed_at": "2026-04-06T12:00:00Z",
            "ip_address": "1.2.3.4",
        })
        assert len(result) == 2
        assert result[0]["agreement"] == "customer_agreement"
        assert result[0]["signed_at"] == "2026-04-06T12:00:00Z"
        assert result[0]["ip_address"] == "1.2.3.4"
        assert result[1]["agreement"] == "margin_agreement"

    def test_customer_only(self):
        result = build_agreements({
            "customer_agreement": True,
            "margin_agreement": False,
            "signed_at": "2026-04-06T12:00:00Z",
            "ip_address": "1.2.3.4",
        })
        assert len(result) == 1
        assert result[0]["agreement"] == "customer_agreement"

    def test_margin_only(self):
        result = build_agreements({
            "customer_agreement": False,
            "margin_agreement": True,
            "signed_at": "2026-04-06T12:00:00Z",
            "ip_address": "1.2.3.4",
        })
        assert len(result) == 1
        assert result[0]["agreement"] == "margin_agreement"

    def test_neither_agreement(self):
        result = build_agreements({
            "customer_agreement": False,
            "margin_agreement": False,
            "signed_at": "2026-04-06T12:00:00Z",
            "ip_address": "1.2.3.4",
        })
        assert result == []

    def test_empty_dict(self):
        assert build_agreements({}) == []


# ---------------------------------------------------------------------------
# build_alpaca_payload
# ---------------------------------------------------------------------------


def _make_profile(**overrides) -> MagicMock:
    """Create a mock UserProfile with all required fields."""
    defaults = {
        "email": "riley@example.com",
        "phone_number": "+15551234567",
        "first_name": "Riley",
        "middle_name": None,
        "last_name": "Johnson",
        "date_of_birth": date(1998, 3, 15),
        "street_address": ["123 Main St", "Apt 4B"],
        "city": "New York",
        "state": "NY",
        "postal_code": "10001",
        "country_of_citizenship": "USA",
        "country_of_birth": "USA",
        "country_of_tax_residence": "USA",
        "disclosures": {
            "is_control_person": False,
            "is_affiliated_exchange_or_finra": False,
            "is_politically_exposed": False,
            "immediate_family_exposed": False,
        },
        "agreements_signed": {
            "customer_agreement": True,
            "margin_agreement": True,
            "signed_at": "2026-04-06T12:00:00Z",
            "ip_address": "1.2.3.4",
        },
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_financial(**overrides) -> MagicMock:
    """Create a mock UserFinancialProfile with all required fields."""
    defaults = {
        "annual_income": "$50K \u2013 $99K",
        "net_worth": "$100K \u2013 $250K",
        "liquid_net_worth": "$25K \u2013 $50K",
        "time_horizon": "5 \u2013 10 years",
        "risk_scenario_response": "hold",
        "max_loss_tolerance": "15-25%",
        "experience_level": "invest_regularly",
        "investment_goals": ["grow_wealth", "retirement"],
        "funding_sources": ["employment_income", "savings"],
        "employment_info": {"employment_status": "employed", "employer_name": "Acme Inc"},
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


class TestBuildAlpacaPayload:

    def test_full_payload_structure(self):
        profile = _make_profile()
        financial = _make_financial()
        payload = build_alpaca_payload(profile, financial, "412-73-8256", "USA_SSN")

        # Top-level keys
        assert set(payload.keys()) == {"contact", "identity", "disclosures", "agreements"}

        # Contact
        assert payload["contact"]["email_address"] == "riley@example.com"
        assert payload["contact"]["phone_number"] == "+15551234567"
        assert payload["contact"]["street_address"] == ["123 Main St", "Apt 4B"]
        assert payload["contact"]["city"] == "New York"
        assert payload["contact"]["state"] == "NY"
        assert payload["contact"]["postal_code"] == "10001"

        # Identity — direct fields
        assert payload["identity"]["given_name"] == "Riley"
        assert payload["identity"]["family_name"] == "Johnson"
        assert payload["identity"]["date_of_birth"] == "1998-03-15"
        assert payload["identity"]["tax_id"] == "412-73-8256"
        assert payload["identity"]["tax_id_type"] == "USA_SSN"
        assert payload["identity"]["country_of_citizenship"] == "USA"
        assert payload["identity"]["funding_source"] == ["employment_income", "savings"]

        # Identity — derived fields
        assert payload["identity"]["annual_income_min"] == "50000"
        assert payload["identity"]["annual_income_max"] == "100000"
        assert payload["identity"]["total_net_worth_min"] == "100000"
        assert payload["identity"]["total_net_worth_max"] == "250000"
        assert payload["identity"]["liquid_net_worth_min"] == "25000"
        assert payload["identity"]["liquid_net_worth_max"] == "50000"
        assert payload["identity"]["investment_time_horizon"] == "6_to_10_years"
        assert payload["identity"]["liquidity_needs"] == "does_not_matter"
        assert payload["identity"]["risk_tolerance"] == "moderate"
        assert payload["identity"]["investment_objective"] == "growth"
        assert payload["identity"]["investment_experience_with_stocks"] == "1_to_5_years"
        assert payload["identity"]["investment_experience_with_options"] == "none"
        assert payload["identity"]["employment_status"] == "employed"

        # middle_name omitted when None
        assert "middle_name" not in payload["identity"]

        # Disclosures — passed through directly
        assert payload["disclosures"]["is_control_person"] is False
        assert payload["disclosures"]["is_politically_exposed"] is False

        # Agreements — constructed as array
        assert len(payload["agreements"]) == 2
        assert payload["agreements"][0]["agreement"] == "customer_agreement"
        assert payload["agreements"][1]["agreement"] == "margin_agreement"

    def test_middle_name_included_when_present(self):
        profile = _make_profile(middle_name="James")
        financial = _make_financial()
        payload = build_alpaca_payload(profile, financial, "412-73-8256", "USA_SSN")

        assert payload["identity"]["middle_name"] == "James"

    def test_country_defaults_to_usa_when_none(self):
        profile = _make_profile(
            country_of_citizenship=None,
            country_of_birth=None,
            country_of_tax_residence=None,
        )
        financial = _make_financial()
        payload = build_alpaca_payload(profile, financial, "412-73-8256", "USA_SSN")

        assert payload["identity"]["country_of_citizenship"] == "USA"
        assert payload["identity"]["country_of_birth"] == "USA"
        assert payload["identity"]["country_of_tax_residence"] == "USA"

    def test_phone_defaults_to_empty_string_when_none(self):
        profile = _make_profile(phone_number=None)
        financial = _make_financial()
        payload = build_alpaca_payload(profile, financial, "412-73-8256", "USA_SSN")

        assert payload["contact"]["phone_number"] == ""


# ---------------------------------------------------------------------------
# OnboardingSubmitRequest tax_id validation
# ---------------------------------------------------------------------------


class TestTaxIdValidation:

    def test_valid_ssn_with_dashes(self):
        req = OnboardingSubmitRequest(tax_id="412-73-8256")
        assert req.tax_id == "412-73-8256"

    def test_valid_ssn_no_dashes(self):
        req = OnboardingSubmitRequest(tax_id="412738256")
        assert req.tax_id == "412738256"

    def test_too_few_digits(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="12345")

    def test_too_many_digits(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="1234567890")

    def test_area_number_000(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="000-45-6789")

    def test_area_number_666(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="666-45-6789")

    def test_area_number_900_plus(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="900-45-6789")

    def test_group_number_00(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="123-00-6789")

    def test_serial_number_0000(self):
        with pytest.raises(Exception):
            OnboardingSubmitRequest(tax_id="123-45-0000")

    def test_ascending_sequence_rejected(self):
        with pytest.raises(Exception, match="Sequential SSN"):
            OnboardingSubmitRequest(tax_id="123-45-6789")

    def test_descending_sequence_rejected(self):
        with pytest.raises(Exception, match="Sequential SSN"):
            OnboardingSubmitRequest(tax_id="987-65-4321")

    def test_all_same_digit_rejected(self):
        for d in ("111111111", "555555555", "999-99-9999"):
            with pytest.raises(Exception, match="All-same-digit"):
                OnboardingSubmitRequest(tax_id=d)


class TestExtractTaxIdLast4:

    def test_dashed_format(self):
        assert extract_tax_id_last_4("412-73-8256") == "8256"

    def test_undashed_format(self):
        assert extract_tax_id_last_4("412738256") == "8256"

    def test_strips_arbitrary_non_digits(self):
        assert extract_tax_id_last_4(" 412 73 8256 ") == "8256"


class TestValidateCompleteness:

    def _complete_profile(self, **overrides) -> MagicMock:
        defaults = {
            "first_name": "Riley",
            "last_name": "Johnson",
            "date_of_birth": date(1998, 3, 15),
            "email": "riley@example.com",
            "street_address": ["123 Main St"],
            "city": "New York",
            "state": "NY",
            "postal_code": "10001",
            "country_of_citizenship": "USA",
            "disclosures": {"is_control_person": False},
            "agreements_signed": {
                "customer_agreement": True,
                "signed_at": "2026-04-06T12:00:00Z",
                "ip_address": "1.2.3.4",
            },
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def _complete_financial(self) -> MagicMock:
        return MagicMock(
            annual_income="$50K – $99K",
            net_worth="$100K – $250K",
            liquid_net_worth="$25K – $50K",
            time_horizon="5 – 10 years",
            risk_scenario_response="hold",
            max_loss_tolerance="15-25%",
            experience_level="invest_regularly",
            investment_goals=["grow_wealth"],
            funding_sources=["employment_income"],
            employment_info={"employment_status": "employed"},
        )

    def test_passes_when_all_fields_present(self):
        validate_completeness(self._complete_profile(), self._complete_financial())

    def test_agreements_missing_signed_at_is_reported(self):
        from app.exceptions import IncompleteOnboardingError

        profile = self._complete_profile(
            agreements_signed={"customer_agreement": True, "ip_address": "1.2.3.4"},
        )
        with pytest.raises(IncompleteOnboardingError) as exc_info:
            validate_completeness(profile, self._complete_financial())
        assert "agreements_signed.signed_at" in exc_info.value.missing_fields
