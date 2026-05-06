"""Tests for ``app.ai.models`` (SEV-461, AI v0 plan D9)."""
from app.ai.models import MODELS
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
        "plaid_fernet_key": "test-key",
        "anthropic_api_key": "sk-ant-test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestModelDefaults:
    """Per AI v0 plan D9: Sonnet 4.6 is the main model, Haiku 4.5 the smoke model."""

    def test_main_defaults_to_sonnet_4_6(self):
        assert MODELS.MAIN == "claude-sonnet-4-6"

    def test_smoke_is_haiku_4_5(self):
        assert MODELS.SMOKE == "claude-haiku-4-5-20251001"


class TestAnthropicModelMainOverride:
    """``ANTHROPIC_MODEL_MAIN`` overrides the default at process startup —
    lets us A/B models in prod without redeploy (D9)."""

    def test_settings_default_matches_d9(self):
        s = _make_settings()
        assert s.anthropic_model_main == "claude-sonnet-4-6"

    def test_explicit_kwarg_override(self):
        s = _make_settings(anthropic_model_main="claude-opus-4-7")
        assert s.anthropic_model_main == "claude-opus-4-7"

    def test_env_var_override(self, monkeypatch):
        # Pydantic Settings reads ANTHROPIC_MODEL_MAIN from env when no
        # kwarg is provided — this is the path that flows to MODELS.MAIN
        # at process startup.
        monkeypatch.setenv("ANTHROPIC_MODEL_MAIN", "claude-opus-4-7")
        s = _make_settings()
        assert s.anthropic_model_main == "claude-opus-4-7"
