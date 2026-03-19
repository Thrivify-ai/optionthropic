from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    poll_interval_seconds: int = 45

    # Database
    database_url: str = "postgresql+asyncpg://optionthropic:optionthropic_secret@localhost:5432/optionthropic"

    # Security
    secret_key: str = "change-me-to-a-long-random-string"
    access_token_expire_minutes: int = 60
    algorithm: str = "HS256"

    # Data Source
    data_source: Literal["NSE", "ZERODHA", "ANGEL"] = "NSE"
    nse_api_url: str = "https://www.nseindia.com"
    zerodha_api_key: str = ""
    zerodha_access_token: str = ""
    angel_api_key: str = ""
    angel_client_id: str = ""
    angel_password: str = ""
    angel_totp_secret: str = ""

    # AI
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ai_provider: Literal["openai", "anthropic", "bedrock"] = "openai"
    ai_cache_ttl_seconds: int = 300
    ai_cache_ttl_market_open_seconds: int = 300
    ai_cache_ttl_market_closed_seconds: int = 21600
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    bedrock_region: str = "ap-south-1"

    # Shared cache
    redis_url: str = ""
    dashboard_cache_ttl_market_open_seconds: int = 15
    dashboard_cache_ttl_market_closed_seconds: int = 14400
    startup_warm_caches: bool = True

    # AWS
    aws_region: str = "ap-south-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    sqs_queue_url: str = ""

    # Cognito
    use_cognito: bool = False
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""

    # Supported symbols
    supported_symbols: list[str] = ["NIFTY", "BANKNIFTY", "SENSEX"]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
