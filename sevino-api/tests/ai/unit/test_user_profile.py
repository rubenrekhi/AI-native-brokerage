"""Unit tests for ``build_user_profile_context`` — the per-user system block.

The render must be deterministic (byte-stable for a given profile state) so it
never busts its own cache breakpoint, and must include only populated,
tailoring-relevant fields — never raw PII.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.ai.utils.user_profile import build_user_profile_context


def _profile(preferred_name=None, first_name=None, **extra):
    return SimpleNamespace(
        preferred_name=preferred_name, first_name=first_name, **extra
    )


def _financial(**fields):
    base = {
        "experience_level": None,
        "risk_tolerance": None,
        "time_horizon": None,
        "max_loss_tolerance": None,
        "income_stability": None,
        "annual_income": None,
        "net_worth": None,
        "liquid_net_worth": None,
        "investment_goals": None,
        "financial_worries": None,
    }
    base.update(fields)
    return SimpleNamespace(**base)


class TestBuildUserProfileContext:
    def test_none_profile_and_financial_returns_none(self):
        assert build_user_profile_context(None, None) is None

    def test_empty_profile_and_financial_returns_none(self):
        assert build_user_profile_context(_profile(), _financial()) is None

    def test_prefers_preferred_name_over_first_name(self):
        block = build_user_profile_context(
            _profile(preferred_name="Jane", first_name="Janet"), None
        )
        assert block is not None
        assert "speaking with Jane." in block
        assert "Janet" not in block

    def test_falls_back_to_first_name(self):
        block = build_user_profile_context(_profile(first_name="Janet"), None)
        assert "speaking with Janet." in block

    def test_name_only_has_no_fact_bullets(self):
        block = build_user_profile_context(_profile(preferred_name="Jane"), None)
        assert block.startswith("## About the user")
        assert "\n- " not in block

    def test_renders_scalar_and_list_fields(self):
        block = build_user_profile_context(
            _profile(preferred_name="Jane"),
            _financial(
                experience_level="invest_regularly",
                risk_tolerance="moderate",
                annual_income="$50K – $99K",
                investment_goals=["grow_wealth", "retirement"],
            ),
        )
        # snake_case codes are humanized; display-ready strings pass through.
        assert "- Investing experience: invest regularly" in block
        assert "- Risk tolerance: moderate" in block
        assert "- Annual income: $50K – $99K" in block
        assert "- Investing goals: grow wealth, retirement" in block

    def test_skips_missing_and_empty_fields(self):
        block = build_user_profile_context(
            _profile(preferred_name="Jane"),
            _financial(
                risk_tolerance="moderate", time_horizon="", investment_goals=[]
            ),
        )
        assert "- Risk tolerance: moderate" in block
        assert "Time horizon" not in block
        assert "Investing goals" not in block

    def test_financial_only_uses_generic_intro(self):
        block = build_user_profile_context(
            None, _financial(risk_tolerance="moderate")
        )
        assert block is not None
        assert "speaking with" not in block
        assert "- Risk tolerance: moderate" in block

    def test_field_order_is_fixed(self):
        # Experience before risk before goals regardless of construction order
        # — determinism guards the cache breakpoint.
        block = build_user_profile_context(
            _profile(preferred_name="Jane"),
            _financial(
                investment_goals=["retirement"],
                risk_tolerance="moderate",
                experience_level="beginner",
            ),
        )
        assert block.index("Investing experience") < block.index(
            "Risk tolerance"
        )
        assert block.index("Risk tolerance") < block.index("Investing goals")

    def test_deterministic_for_equivalent_input(self):
        def make():
            return (
                _profile(preferred_name="Jane"),
                _financial(
                    risk_tolerance="moderate",
                    investment_goals=["grow_wealth"],
                ),
            )

        assert build_user_profile_context(*make()) == build_user_profile_context(
            *make()
        )

    def test_non_string_list_items_skipped(self):
        block = build_user_profile_context(
            _profile(preferred_name="Jane"),
            _financial(investment_goals=["grow_wealth", None, 123, ""]),
        )
        assert "- Investing goals: grow wealth" in block

    def test_excludes_pii_even_when_columns_populated(self):
        """PII must never reach the LLM, even when the columns hold data.

        The render is allowlist-based, so contact details, address, DOB, and
        SSN-last-4 should leave no trace. This locks in the compliance intent:
        a future edit that adds one of these columns to the field lists fails
        here.
        """
        block = build_user_profile_context(
            _profile(
                preferred_name="Jane",
                email="jane-pii@example.com",
                date_of_birth=date(1990, 5, 14),
                phone_number="+15558675309",
                street_address=["999 Secret Street", "Unit 56"],
                city="Confidentialville",
                state="ZZ",
                postal_code="PIIZIP",
                tax_id_last_4="6789",
            ),
            _financial(
                risk_tolerance="moderate",
                date_of_birth=date(1990, 5, 14),
                employment_info={"employer_name": "AcmeSecretCorp"},
                funding_sources=["SecretInheritanceFund"],
                risk_scenario_response="WouldSellEverythingInPanic",
            ),
        )
        assert block is not None
        assert "- Risk tolerance: moderate" in block
        # Underscore-free canaries: _humanize would otherwise rewrite them, so
        # an underscored value could slip past a substring check.
        for pii in (
            "jane-pii@example.com",
            "1990",
            "8675309",
            "Secret Street",
            "Confidentialville",
            "PIIZIP",
            "6789",
            "AcmeSecretCorp",
            "SecretInheritanceFund",
            "WouldSellEverythingInPanic",
        ):
            assert pii not in block
