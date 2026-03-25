from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    @field_validator("database_url", "database_url_direct")
    @classmethod
    def ensure_asyncpg_scheme(cls, v: str) -> str:
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


settings = Settings()
