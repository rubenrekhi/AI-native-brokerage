import pytest
from pydantic import ValidationError

from app.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "environment": "dev",
        "database_url": "postgresql://localhost/test",
        "redis_url": "redis://localhost",
        "supabase_url": "http://localhost",
        "supabase_anon_key": "sb_publishable_test",
        "supabase_service_role_key": "sb_service_role_test",
        "alpaca_api_key": "x",
        "alpaca_secret_key": "x",
        "plaid_client_id": "x",
        "plaid_secret": "x",
        "plaid_env": "sandbox",
        "fmp_api_key": "fmp_test",
        "alpaca_apr_tier_name": "standard",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestCorsOrigins:
    def test_dev_allows_all(self):
        s = _make_settings(environment="dev")
        assert s.cors_origins == ["*"]

    def test_staging_empty(self):
        s = _make_settings(environment="staging")
        assert s.cors_origins == []

    def test_prod_empty(self):
        s = _make_settings(environment="prod")
        assert s.cors_origins == []

    def test_production_normalizes_to_prod(self):
        s = _make_settings(environment="production")
        assert s.environment == "prod"
        assert s.cors_origins == []


class TestSupabaseAnonKey:
    def test_loads_from_input(self):
        s = _make_settings(supabase_anon_key="sb_publishable_abc")
        assert s.supabase_anon_key == "sb_publishable_abc"

    def test_required(self):
        with pytest.raises(ValidationError):
            _make_settings(supabase_anon_key=None)


class TestSupabaseServiceRoleKey:
    def test_optional_in_dev(self):
        s = _make_settings(environment="dev", supabase_service_role_key="")
        assert s.supabase_service_role_key == ""

    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_required_outside_dev(self, env):
        with pytest.raises(ValidationError, match="SUPABASE_SERVICE_ROLE_KEY"):
            _make_settings(environment=env, supabase_service_role_key="")


class TestFmpApiKey:
    def test_loads_from_input(self):
        s = _make_settings(fmp_api_key="fmp_abc")
        assert s.fmp_api_key == "fmp_abc"

    def test_required(self):
        with pytest.raises(ValidationError):
            _make_settings(fmp_api_key=None)


class TestAlpacaAprTierName:
    def test_loads_from_input(self):
        s = _make_settings(alpaca_apr_tier_name="premium")
        assert s.alpaca_apr_tier_name == "premium"

    def test_required(self):
        with pytest.raises(ValidationError):
            _make_settings(alpaca_apr_tier_name=None)


class TestAlpacaDataBaseUrl:
    def test_dev_uses_sandbox(self):
        s = _make_settings(environment="dev")
        assert s.alpaca_data_base_url == "https://data.sandbox.alpaca.markets"

    def test_staging_uses_sandbox(self):
        s = _make_settings(environment="staging")
        assert s.alpaca_data_base_url == "https://data.sandbox.alpaca.markets"

    def test_prod_uses_live(self):
        s = _make_settings(environment="prod")
        assert s.alpaca_data_base_url == "https://data.alpaca.markets"


class TestSentryEnvironment:
    """``sentry_environment`` overrides the env tag for Railway PR-preview
    deploys (so torn-down preview noise is filterable) but leaves the tag
    untouched for real staging/prod (so existing alerts and dashboards
    keyed off ``staging``/``prod`` keep matching). See SEV-433."""

    def test_pr_preview_overrides(self):
        s = _make_settings(
            environment="staging", railway_environment_name="sevino-pr-123"
        )
        assert s.is_pr_preview is True
        assert s.sentry_environment == "sevino-pr-123"

    def test_bare_pr_prefix_does_not_match(self):
        # Guard against regressing to a "pr-" prefix check: Railway's
        # actual env name for Sevino's previews is "sevino-pr-N", not
        # "pr-N", so a bare "pr-" prefix would never fire.
        s = _make_settings(
            environment="staging", railway_environment_name="pr-123"
        )
        assert s.is_pr_preview is False
        assert s.sentry_environment == "staging"

    def test_real_staging_keeps_settings_environment(self):
        s = _make_settings(
            environment="staging", railway_environment_name="staging"
        )
        assert s.is_pr_preview is False
        assert s.sentry_environment == "staging"

    def test_real_prod_keeps_normalized_prod(self):
        # Load-bearing case: Railway names the prod env "production" but
        # settings.environment normalizes to "prod". sentry_environment
        # must return "prod" — not "production" — or existing Sentry
        # alerts keyed off environment=prod silently stop matching.
        s = _make_settings(
            environment="production", railway_environment_name="production"
        )
        assert s.environment == "prod"
        assert s.is_pr_preview is False
        assert s.sentry_environment == "prod"

    def test_unset_falls_back_to_settings_environment(self):
        s = _make_settings(environment="dev", railway_environment_name="")
        assert s.is_pr_preview is False
        assert s.sentry_environment == "dev"
