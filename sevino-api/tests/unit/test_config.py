from app.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "environment": "dev",
        "database_url": "postgresql://localhost/test",
        "redis_url": "redis://localhost",
        "supabase_url": "http://localhost",
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
