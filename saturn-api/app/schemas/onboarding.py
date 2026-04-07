from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class OnboardingStep(str, Enum):
    """Every screen in the onboarding flow that persists data or marks progress."""

    # Phase 1 — Profile
    welcome = "welcome"
    preferred_name = "preferred_name"
    attribution = "attribution"
    financial_worries = "financial_worries"
    investment_goals = "investment_goals"
    date_of_birth = "date_of_birth"
    annual_income = "annual_income"
    net_worth = "net_worth"
    liquid_net_worth = "liquid_net_worth"
    income_stability = "income_stability"
    time_horizon = "time_horizon"
    risk_scenario = "risk_scenario"
    max_loss_tolerance = "max_loss_tolerance"
    experience = "experience"
    risk_disclosure = "risk_disclosure"

    # Phase 2 — KYC
    kyc_intro = "kyc_intro"
    legal_name = "legal_name"
    ssn = "ssn"
    address = "address"
    citizenship = "citizenship"
    employment = "employment"
    funding_sources = "funding_sources"
    disclosures = "disclosures"
    agreements = "agreements"

    # Terminal
    submitted = "submitted"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class OnboardingPatchRequest(BaseModel):
    """Incremental save — called after every screen. All fields optional except step."""

    step: OnboardingStep

    # Phase 1 — user_profiles fields
    preferred_name: str | None = None
    date_of_birth: date | None = None
    attribution_source: str | None = None
    risk_disclosure_acknowledged_at: datetime | None = None

    # Phase 1 — user_financial_profiles fields
    financial_worries: list[str] | None = None
    investment_goals: list[str] | None = None
    annual_income: str | None = None
    net_worth: str | None = None
    liquid_net_worth: str | None = None
    income_stability: str | None = None
    time_horizon: str | None = None
    risk_scenario_response: str | None = None
    max_loss_tolerance: str | None = None
    experience_level: str | None = None

    # Phase 2 — user_profiles fields (KYC)
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    street_address: list[str] | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country_of_citizenship: str | None = None
    country_of_birth: str | None = None
    country_of_tax_residence: str | None = None

    # Phase 2 — user_financial_profiles fields
    employment_info: dict[str, Any] | None = None
    funding_sources: list[str] | None = None

    # Phase 2 — JSONB on user_profiles
    disclosures: dict[str, Any] | None = None
    agreements_signed: dict[str, Any] | None = None


class OnboardingSubmitRequest(BaseModel):
    """Final KYC submission — SSN forwarded to Alpaca, never stored."""

    tax_id: str
    tax_id_type: str = "USA_SSN"


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ProfileData(BaseModel):
    preferred_name: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    email: str | None = None
    phone_number: str | None = None
    attribution_source: str | None = None
    street_address: list[str] | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country_of_citizenship: str | None = None
    country_of_birth: str | None = None
    country_of_tax_residence: str | None = None
    disclosures: dict[str, Any] | None = None
    agreements_signed: dict[str, Any] | None = None
    risk_disclosure_acknowledged_at: datetime | None = None

    model_config = {"from_attributes": True}


class FinancialProfileData(BaseModel):
    financial_worries: list[str] | None = None
    investment_goals: list[str] | None = None
    annual_income: str | None = None
    net_worth: str | None = None
    liquid_net_worth: str | None = None
    income_stability: str | None = None
    time_horizon: str | None = None
    risk_scenario_response: str | None = None
    max_loss_tolerance: str | None = None
    experience_level: str | None = None
    employment_info: dict[str, Any] | None = None
    funding_sources: list[str] | None = None

    model_config = {"from_attributes": True}


class OnboardingStatusResponse(BaseModel):
    onboarding_completed: bool
    onboarding_step: OnboardingStep | None
    account_status: str | None = None
    kyc_results: dict[str, Any] | None = None
    profile: ProfileData
    financial_profile: FinancialProfileData | None = None


class OnboardingSubmitResponse(BaseModel):
    account_status: str
    alpaca_account_id: str
