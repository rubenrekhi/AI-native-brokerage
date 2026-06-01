"""Unit tests for US state-code validation on schemas that forward `state` to Alpaca.

Regression coverage for SEV-430: iOS sent "ON" (Ontario) and Alpaca rejected the
KYC submission. The gate now lives at our Pydantic boundary.
"""

import pytest
from pydantic import ValidationError

from app.schemas.onboarding import OnboardingPatchRequest
from app.schemas.settings import ProfileUpdateRequest


class TestOnboardingPatchRequestState:
    def test_rejects_canadian_province(self):
        with pytest.raises(ValidationError) as exc_info:
            OnboardingPatchRequest(step="address", state="ON")
        assert "state must be a valid US state code" in str(exc_info.value)

    def test_accepts_us_state(self):
        req = OnboardingPatchRequest(step="address", state="CA")
        assert req.state == "CA"

    def test_normalizes_lowercase_and_whitespace(self):
        req = OnboardingPatchRequest(step="address", state=" ny ")
        assert req.state == "NY"

    def test_accepts_dc_and_territory(self):
        assert OnboardingPatchRequest(step="address", state="DC").state == "DC"
        assert OnboardingPatchRequest(step="address", state="PR").state == "PR"

    def test_state_optional(self):
        req = OnboardingPatchRequest(step="address")
        assert req.state is None

    @pytest.mark.parametrize("bad", ["ON", "QC", "BC", "XX", "ZZ", "", "California"])
    def test_rejects_invalid(self, bad):
        with pytest.raises(ValidationError):
            OnboardingPatchRequest(step="address", state=bad)


class TestProfileUpdateRequestState:
    def test_rejects_canadian_province(self):
        with pytest.raises(ValidationError) as exc_info:
            ProfileUpdateRequest(state="ON")
        assert "state must be a valid US state code" in str(exc_info.value)

    def test_accepts_and_normalizes_us_state(self):
        assert ProfileUpdateRequest(state="ca").state == "CA"

    def test_blank_state_collapses_to_none(self):
        # `_strip_strings` turns "" into None; another field satisfies the
        # at-least-one-field model validator.
        req = ProfileUpdateRequest(state="", city="Austin")
        assert req.state is None
