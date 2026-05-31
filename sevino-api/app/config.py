import ssl as _ssl
from typing import Any

from arq.connections import RedisSettings
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.retry import Retry

_PROD_KEYWORDS = {"prod", "production"}
_STAGING_KEYWORDS = {"staging"}
_DEV_KEYWORDS = {"dev", "development"}


def _normalize_env(raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned in _PROD_KEYWORDS:
        return "prod"
    if cleaned in _STAGING_KEYWORDS:
        return "staging"
    if cleaned in _DEV_KEYWORDS:
        return "dev"
    return cleaned


def get_ssl_connect_args(environment: str) -> dict[str, Any]:
    """Return connect_args with SSL context for hosted environments, empty dict for dev."""
    if environment in ("prod", "staging"):
        ctx = _ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = _ssl.CERT_NONE
        return {"ssl": ctx}
    return {}


class Settings(BaseSettings):
    APP_NAME: str = "Sevino API"
    APP_DESCRIPTION: str = "Backend API for the Sevino investment app"
    APP_VERSION: str = "0.1.0"

    environment: str = "dev"
    database_url: str
    database_url_direct: str = ""
    redis_url: str
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    api_key: str = ""
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_apr_tier_name: str
    cash_sweep_fdic_insured_limit: str = "2500000"
    cash_sweep_payout_cadence: str = "monthly"
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str
    plaid_fernet_key: str
    # Per-environment webhook URL Plaid posts item state changes to. Unset in
    # dev (no public ingress); set to `https://<host>/v1/plaid/webhooks` in
    # staging/prod. Unset disables webhook delivery for newly-linked items.
    plaid_webhook_url: str | None = None
    anthropic_api_key: str
    sentry_dsn: str = ""
    railway_environment_name: str = ""
    anthropic_model_main: str = "claude-sonnet-4-6"
    radar_llm_model: str = "claude-sonnet-4-6"
    anthropic_enable_web_search: bool = False
    anthropic_enable_web_fetch: bool = False
    anthropic_enable_code_execution: bool = False
    anthropic_web_search_max_uses: int = 5
    anthropic_web_fetch_max_uses: int = 5
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://us.cloud.langfuse.com"
    fmp_api_key: str

    @property
    def plaid_fernet_keys(self) -> list[str]:
        return [k.strip() for k in self.plaid_fernet_key.split(",") if k.strip()]

    @property
    def is_pr_preview(self) -> bool:
        # Railway's PR-preview env names follow the project's environment
        # template, which for Sevino is "sevino-pr-{number}" (visible in
        # Railway → service → variables → RAILWAY_ENVIRONMENT_NAME). If
        # the template is ever changed in Railway, this prefix must be
        # updated to match or PR-preview filtering silently stops working.
        return self.railway_environment_name.startswith("sevino-pr-")

    @property
    def sentry_environment(self) -> str:
        # PR previews get their own tag (sevino-pr-NNN) so noise from
        # torn-down previews is filterable. Real staging/prod keep
        # settings.environment ("staging"/"prod") so existing Sentry alerts
        # and dashboards keyed off those values don't silently break —
        # Railway's env name for prod is "production", which would not
        # match a "prod"-keyed alert.
        return self.railway_environment_name if self.is_pr_preview else self.environment

    @property
    def show_docs(self) -> bool:
        return self.environment != "prod"

    @property
    def alpaca_base_url(self) -> str:
        if self.environment == "prod":
            return "https://broker-api.alpaca.markets"
        return "https://broker-api.sandbox.alpaca.markets"

    @property
    def alpaca_data_base_url(self) -> str:
        if self.environment == "prod":
            return "https://data.alpaca.markets"
        return "https://data.sandbox.alpaca.markets"

    @property
    def alpaca_auth_url(self) -> str:
        if self.environment == "prod":
            return "https://authx.alpaca.markets"
        return "https://authx.sandbox.alpaca.markets"

    @property
    def cors_origins(self) -> list[str]:
        if self.environment == "dev":
            return ["*"]
        return []

    model_config = {"env_file": ".env"}

    @field_validator("environment")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        return _normalize_env(v)

    @field_validator("database_url", "database_url_direct")
    @classmethod
    def ensure_asyncpg_scheme(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def require_service_role_key_outside_dev(self) -> "Settings":
        # The service-role key is required for privileged admin operations
        # (e.g. DELETE /v1/settings/account). Allow empty in dev for
        # convenience, fail fast at boot in staging/prod so a misconfigured
        # deploy can't surface as a per-request 503.
        if self.environment != "dev" and not self.supabase_service_role_key:
            raise ValueError(
                "SUPABASE_SERVICE_ROLE_KEY is required outside of dev"
            )
        return self



settings = Settings()


def get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from the configured URL with retry/reconnect support."""
    base = RedisSettings.from_dsn(settings.redis_url)
    base.conn_retries = 10
    base.conn_retry_delay = 1
    base.retry_on_timeout = True
    base.retry_on_error = [RedisConnectionError]
    base.retry = Retry(backoff=ExponentialBackoff(), retries=5)
    return base
