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
