from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    database_url_direct: str = ""
    redis_url: str
    supabase_jwt_secret: str
    alpaca_api_key: str
    alpaca_secret_key: str
    plaid_client_id: str
    plaid_secret: str
    plaid_env: str

    model_config = {"env_file": ".env"}


settings = Settings()
