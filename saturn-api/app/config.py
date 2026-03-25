from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

_PROD_KEYWORDS = {"prod", "production"}
_DEV_KEYWORDS = {"dev", "development"}


def _normalize_env(raw: str) -> str:
    cleaned = raw.strip().lower()
    if cleaned in _PROD_KEYWORDS:
        return "prod"
    if cleaned in _DEV_KEYWORDS:
        return "dev"
    return cleaned


def _ensure_ssl_param(url: str, *, require: bool) -> str:
    if not url:
        return url
    mode = "require" if require else "disable"
    sep = "&" if "?" in url else "?"
    # Replace existing sslmode param if present
    if "sslmode=" in url:
        import re
        return re.sub(r"sslmode=[^&]*", f"sslmode={mode}", url)
    return f"{url}{sep}sslmode={mode}"


class Settings(BaseSettings):
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
    def apply_ssl_mode(self) -> "Settings":
        require = self.environment == "prod"
        self.database_url = _ensure_ssl_param(self.database_url, require=require)
        self.database_url_direct = _ensure_ssl_param(
            self.database_url_direct, require=require
        )
        return self


settings = Settings()
