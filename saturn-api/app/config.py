import ssl as _ssl
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings

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
    APP_NAME: str = "Saturn API"
    APP_DESCRIPTION: str = "Backend API for the Saturn investment app by Sevino"
    APP_VERSION: str = "0.1.0"

    environment: str = "dev"
    database_url: str
    database_url_direct: str = ""
    redis_url: str
    supabase_url: str
    alpaca_api_key: str
    alpaca_secret_key: str
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str

    @property
    def show_docs(self) -> bool:
        return self.environment != "prod"

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
