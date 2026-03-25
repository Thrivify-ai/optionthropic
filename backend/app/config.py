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
    fast_tick_poll_seconds: int = 5

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
    global_news_enabled: bool = True
    global_news_poll_market_open_seconds: int = 300
    global_news_poll_market_closed_seconds: int = 3600
    global_news_cache_ttl_market_open_seconds: int = 300
    global_news_cache_ttl_market_closed_seconds: int = 21600
    global_news_lookback_hours: int = 36
    global_news_limit: int = 10
    global_news_timeout_seconds: int = 8
    global_news_rss_urls: list[str] = [
        "https://news.google.com/rss/search?q=(Federal%20Reserve%20OR%20FOMC%20OR%20inflation%20OR%20CPI%20OR%20payrolls%20OR%20bond%20yields%20OR%20rate%20cut%20OR%20rate%20hike)&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=(oil%20OR%20crude%20OR%20OPEC%20OR%20Middle%20East%20OR%20sanctions%20OR%20tariff%20OR%20war)&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=(RBI%20OR%20rupee%20OR%20USDINR%20OR%20China%20stimulus%20OR%20Asia%20markets%20OR%20India%20markets)&hl=en-IN&gl=IN&ceid=IN:en",
    ]

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
