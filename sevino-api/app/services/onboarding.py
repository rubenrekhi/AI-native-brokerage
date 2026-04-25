import re
import uuid
from datetime import datetime, timezone
from typing import Any

import sentry_sdk
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brokerage_account import BrokerageAccount
from app.models.user_financial_profile import UserFinancialProfile
from app.models.user_profile import UserProfile
from app.repositories.brokerage_account import BrokerageAccountRepository
from app.repositories.financial_profile import FinancialProfileRepository
from app.repositories.user_profile import UserProfileRepository
from app.schemas.onboarding import (
    FinancialProfileData,
    OnboardingPatchRequest,
    OnboardingStatusResponse,
    ProfileData,
)
from sqlalchemy.exc import IntegrityError

from app.exceptions import ConflictError, IncompleteOnboardingError, NotFoundError
from app.services.alpaca_broker import AlpacaBrokerService

logger = structlog.get_logger(__name__)


INCOME_RANGES: dict[str, tuple[str, str]] = {
    "Under $25K": ("0", "25000"),
    "$25K \u2013 $49K": ("25000", "50000"),
    "$50K \u2013 $99K": ("50000", "100000"),
    "$100K \u2013 $199K": ("100000", "200000"),
    "$200K \u2013 $499K": ("200000", "500000"),
    "$500K+": ("500000", "1000000"),
}

NET_WORTH_RANGES: dict[str, tuple[str, str]] = {
    "Under $10K": ("0", "10000"),
    "$10K \u2013 $50K": ("10000", "50000"),
    "$50K \u2013 $100K": ("50000", "100000"),
    "$100K \u2013 $250K": ("100000", "250000"),
    "$250K \u2013 $500K": ("250000", "500000"),
    "$500K \u2013 $1M": ("500000", "1000000"),
    "$1M+": ("1000000", "5000000"),
}

LIQUID_NET_WORTH_RANGES: dict[str, tuple[str, str]] = {
    "Under $10K": ("0", "10000"),
    "$10K \u2013 $25K": ("10000", "25000"),
    "$25K \u2013 $50K": ("25000", "50000"),
    "$50K \u2013 $100K": ("50000", "100000"),
    "$100K \u2013 $250K": ("100000", "250000"),
    "$250K+": ("250000", "1000000"),
}

TIME_HORIZON_MAP: dict[str, tuple[str, str]] = {
    "Less than 2 years": ("1_to_2_years", "very_important"),
    "2 \u2013 5 years": ("3_to_5_years", "somewhat_important"),
    "5 \u2013 10 years": ("6_to_10_years", "does_not_matter"),
    "10 \u2013 20 years": ("more_than_10_years", "does_not_matter"),
    "20+ years": ("more_than_10_years", "does_not_matter"),
}

GOAL_TO_OBJECTIVE: dict[str, str] = {
    "grow_wealth": "growth",
    "save_for_goal": "growth",
    "retirement": "growth",
    "safety_net": "preserve_wealth",
    "learn_to_invest": "growth",
    "make_cash_work": "preserve_wealth",
}

EXPERIENCE_MAP: dict[str, str] = {
    "never_invested": "none",
    "invested_little": "1_to_5_years",
    "invest_regularly": "1_to_5_years",
    "actively_manage": "over_5_years",
    "advanced_strategies": "over_5_years",
}

EMPLOYMENT_STATUS_MAP: dict[str, str] = {
    "employed": "employed",
    "self_employed": "employed",
    "unemployed": "unemployed",
    "student": "student",
    "retired": "retired",
}

# Fields that belong to user_profiles vs user_financial_profiles.
# Note: tax_id_last_4 is intentionally excluded — it is set only during
# submit_kyc, never via the incremental save_step PATCH from the client.
_PROFILE_FIELDS = {
    "preferred_name",
    "date_of_birth",
    "phone_number",
    "attribution_source",
    "risk_disclosure_acknowledged_at",
    "first_name",
    "middle_name",
    "last_name",
    "street_address",
    "city",
    "state",
    "postal_code",
    "country_of_citizenship",
    "country_of_birth",
    "country_of_tax_residence",
    "disclosures",
    "agreements_signed",
}

_FINANCIAL_FIELDS = {
    "financial_worries",
    "investment_goals",
    "annual_income",
    "net_worth",
    "liquid_net_worth",
    "income_stability",
    "time_horizon",
    "risk_scenario_response",
    "max_loss_tolerance",
    "experience_level",
    "employment_info",
    "funding_sources",
}


def derive_risk_tolerance(scenario: str, max_loss: str) -> str:
    """
    Mapping matrix from onboarding doc (screens 14 + 15):

    | Scenario Response          | Max Drop       | → risk_tolerance |
    |----------------------------|----------------|------------------|
    | sell_everything / sell_some | 0-5% or 5-15%  | conservative     |
    | sell_everything / sell_some | 15-25% or above | moderate         |
    | hold / not_sure            | 0-5% or 5-15%  | conservative     |
    | hold / not_sure            | 15-25% or above | moderate         |
    | buy_more                   | 0-5% to 15-25% | moderate         |
    | buy_more                   | 25-40% or 40%+ | aggressive       |
    """
    low_loss = max_loss in ("0-5%", "5-15%")
    high_loss = max_loss in ("25-40%", "40%+")

    if scenario in ("sell_everything", "sell_some"):
        return "conservative" if low_loss else "moderate"
    if scenario in ("hold", "not_sure"):
        return "conservative" if low_loss else "moderate"
    if scenario == "buy_more":
        return "significant_risk" if high_loss else "moderate"
    return "moderate"


def derive_investment_objective(goals: list[str]) -> str:
    """Based on FIRST selected goal from screen 6."""
    for goal in goals:
        if goal in GOAL_TO_OBJECTIVE:
            return GOAL_TO_OBJECTIVE[goal]
    return "growth"


def map_range(value: str, ranges: dict[str, tuple[str, str]]) -> tuple[str, str]:
    if value in ranges:
        return ranges[value]
    first = next(iter(ranges.values()))
    logger.warning("unknown_range_value", value=value)
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("alert_type", "unknown_range_value")
        scope.set_context(
            "range_lookup",
            {"value": value, "known_keys": list(ranges.keys())},
        )
        sentry_sdk.capture_message(
            f"unknown_range_value mapped to fallback: {value!r}",
            level="warning",
        )
    return first


def map_time_horizon(time_horizon: str) -> tuple[str, str]:
    return TIME_HORIZON_MAP.get(time_horizon, ("3_to_5_years", "does_not_matter"))


def map_experience(experience_level: str) -> str:
    return EXPERIENCE_MAP.get(experience_level, "none")


def map_employment_status(employment_info: dict[str, Any]) -> str:
    raw_status = employment_info.get("employment_status", "").lower()
    return EMPLOYMENT_STATUS_MAP.get(raw_status, "employed")


def extract_tax_id_last_4(tax_id: str) -> str:
    """Strip non-digits from a tax ID (e.g. '123-45-6789') and return last 4."""
    return re.sub(r"[^0-9]", "", tax_id)[-4:]


def build_agreements(agreements_data: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    signed_at = agreements_data.get("signed_at")
    ip_address = agreements_data.get("ip_address")
    if agreements_data.get("customer_agreement"):
        result.append(
            {"agreement": "customer_agreement", "signed_at": signed_at, "ip_address": ip_address}
        )
    if agreements_data.get("margin_agreement"):
        result.append(
            {"agreement": "margin_agreement", "signed_at": signed_at, "ip_address": ip_address}
        )
    return result


class OnboardingService:

    @staticmethod
    async def save_step(
        db: AsyncSession, user_id: uuid.UUID, data: OnboardingPatchRequest
    ) -> str:
        provided = data.model_dump(exclude_none=True, exclude={"step"})

        profile_updates: dict[str, Any] = {"onboarding_step": data.step}
        financial_updates: dict[str, Any] = {}

        for key, value in provided.items():
            if key in _PROFILE_FIELDS:
                profile_updates[key] = value
            elif key in _FINANCIAL_FIELDS:
                financial_updates[key] = value

        await UserProfileRepository.update_fields(db, user_id, **profile_updates)

        if financial_updates:
            await FinancialProfileRepository.upsert(db, user_id, **financial_updates)

        return data.step

    @staticmethod
    async def get_status(
        db: AsyncSession, user_id: uuid.UUID
    ) -> OnboardingStatusResponse:
        """Load full onboarding state for resume."""
        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            return OnboardingStatusResponse(
                onboarding_completed=False,
                onboarding_step=None,
                profile=ProfileData(),
            )

        financial = await FinancialProfileRepository.get_by_user_id(db, user_id)
        brokerage = await BrokerageAccountRepository.get_by_user_id(db, user_id)

        return OnboardingStatusResponse(
            onboarding_completed=profile.onboarding_completed,
            onboarding_step=profile.onboarding_step,
            account_status=brokerage.account_status if brokerage else None,
            kyc_results=brokerage.kyc_results if brokerage else None,
            profile=ProfileData.model_validate(profile),
            financial_profile=(
                FinancialProfileData.model_validate(financial) if financial else None
            ),
        )

    @staticmethod
    async def submit_kyc(
        db: AsyncSession,
        user_id: uuid.UUID,
        tax_id: str,
        tax_id_type: str,
        alpaca: AlpacaBrokerService,
    ) -> dict[str, str]:
        """Build Alpaca payload from saved data + SSN, submit, create brokerage row."""
        existing = await BrokerageAccountRepository.get_by_user_id(db, user_id)
        if existing is not None:
            raise ConflictError(
                "Brokerage account already exists for this user",
                resource="brokerage_account",
            )

        profile = await UserProfileRepository.get_by_id(db, user_id)
        if profile is None:
            raise NotFoundError("User profile not found", resource="user_profile")

        financial = await FinancialProfileRepository.get_by_user_id(db, user_id)
        if financial is None:
            raise IncompleteOnboardingError(
                "Financial profile not found — complete onboarding first"
            )

        validate_completeness(profile, financial)

        payload = build_alpaca_payload(profile, financial, tax_id, tax_id_type)

        logger.info("submitting_kyc_to_alpaca", user_id=str(user_id))
        result = await alpaca.create_account(payload)

        alpaca_account_id = result["id"]
        account_status = result.get("status", "SUBMITTED")

        try:
            await BrokerageAccountRepository.create(
                db,
                user_id=user_id,
                alpaca_account_id=alpaca_account_id,
                account_status=account_status,
                account_number=result.get("account_number"),
                kyc_results=result.get("kyc_results"),
            )
        except IntegrityError:
            raise ConflictError(
                "Brokerage account already exists for this user",
                resource="brokerage_account",
            )

        await UserProfileRepository.update_fields(
            db,
            user_id,
            onboarding_step="submitted",
            tax_id_last_4=extract_tax_id_last_4(tax_id),
        )

        logger.info(
            "kyc_submitted",
            user_id=str(user_id),
            alpaca_account_id=alpaca_account_id,
            status=account_status,
        )

        return {
            "account_status": account_status,
            "alpaca_account_id": alpaca_account_id,
        }


def validate_completeness(
    profile: UserProfile, financial: UserFinancialProfile
) -> None:
    missing: list[str] = []

    if not profile.first_name:
        missing.append("first_name")
    if not profile.last_name:
        missing.append("last_name")
    if not profile.date_of_birth:
        missing.append("date_of_birth")
    if not profile.email:
        missing.append("email")
    if not profile.street_address:
        missing.append("street_address")
    if not profile.city:
        missing.append("city")
    if not profile.state:
        missing.append("state")
    if not profile.postal_code:
        missing.append("postal_code")
    if not profile.country_of_citizenship:
        missing.append("country_of_citizenship")
    if not profile.disclosures:
        missing.append("disclosures")
    if not profile.agreements_signed:
        missing.append("agreements_signed")
    if not financial.annual_income:
        missing.append("annual_income")
    if not financial.net_worth:
        missing.append("net_worth")
    if not financial.liquid_net_worth:
        missing.append("liquid_net_worth")
    if not financial.time_horizon:
        missing.append("time_horizon")
    if not financial.risk_scenario_response:
        missing.append("risk_scenario_response")
    if not financial.max_loss_tolerance:
        missing.append("max_loss_tolerance")
    if not financial.experience_level:
        missing.append("experience_level")
    if not financial.investment_goals:
        missing.append("investment_goals")
    if not financial.funding_sources:
        missing.append("funding_sources")
    if not financial.employment_info:
        missing.append("employment_info")

    if missing:
        raise IncompleteOnboardingError(
            f"Missing required fields for KYC submission: {', '.join(missing)}",
            missing_fields=missing,
        )


def build_alpaca_payload(
    profile: UserProfile,
    financial: UserFinancialProfile,
    tax_id: str,
    tax_id_type: str,
) -> dict[str, Any]:
    """Construct the full Alpaca POST /v1/accounts payload."""
    income_min, income_max = map_range(financial.annual_income, INCOME_RANGES)
    nw_min, nw_max = map_range(financial.net_worth, NET_WORTH_RANGES)
    lnw_min, lnw_max = map_range(financial.liquid_net_worth, LIQUID_NET_WORTH_RANGES)
    time_horizon_val, liquidity_needs = map_time_horizon(financial.time_horizon)
    risk_tolerance = derive_risk_tolerance(
        financial.risk_scenario_response, financial.max_loss_tolerance
    )
    investment_objective = derive_investment_objective(financial.investment_goals)
    experience = map_experience(financial.experience_level)
    employment_status = map_employment_status(financial.employment_info or {})

    payload: dict[str, Any] = {
        "contact": {
            "email_address": profile.email,
            "phone_number": profile.phone_number or "",
            "street_address": profile.street_address or [],
            "city": profile.city,
            "state": profile.state,
            "postal_code": profile.postal_code,
        },
        "identity": {
            "given_name": profile.first_name,
            "family_name": profile.last_name,
            "date_of_birth": profile.date_of_birth.isoformat(),
            "tax_id": tax_id,
            "tax_id_type": tax_id_type,
            "country_of_citizenship": profile.country_of_citizenship or "USA",
            "country_of_birth": profile.country_of_birth or "USA",
            "country_of_tax_residence": profile.country_of_tax_residence or "USA",
            "funding_source": financial.funding_sources or [],
            "annual_income_min": income_min,
            "annual_income_max": income_max,
            "total_net_worth_min": nw_min,
            "total_net_worth_max": nw_max,
            "liquid_net_worth_min": lnw_min,
            "liquid_net_worth_max": lnw_max,
            "investment_time_horizon": time_horizon_val,
            "liquidity_needs": liquidity_needs,
            "investment_experience_with_stocks": experience,
            "investment_experience_with_options": "none",
            "risk_tolerance": risk_tolerance,
            "investment_objective": investment_objective,
            "employment_status": employment_status,
        },
        "disclosures": profile.disclosures,
        "agreements": build_agreements(profile.agreements_signed or {}),
    }

    if profile.middle_name:
        payload["identity"]["middle_name"] = profile.middle_name

    return payload
