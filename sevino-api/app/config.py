import ssl as _ssl
from typing import Any

from arq.connections import RedisSettings
from pydantic import field_validator
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
    api_key: str = ""
    alpaca_api_key: str
    alpaca_secret_key: str
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str
    sentry_dsn: str = ""

    @property
    def show_docs(self) -> bool:
        return self.environment != "prod"

    @property
    def alpaca_base_url(self) -> str:
        if self.environment == "prod":
            return "https://broker-api.alpaca.markets"
        return "https://broker-api.sandbox.alpaca.markets"

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
