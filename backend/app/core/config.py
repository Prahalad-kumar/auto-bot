from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_ACCESS_TOKEN: str = ""
    DATABASE_URL: str = "postgresql+psycopg://autobot:autobot@postgres:5432/autobot"
    REDIS_URL: str = "redis://redis:6379/0"
    TRADING_MODE: str = "PAPER"
    LIVE_TRADING_ENABLED: bool = False
    MAX_DAILY_LOSS: float = 500.0
    MAX_RISK_PER_TRADE: float = 100.0
    MAX_OPEN_POSITIONS: int = 1
    MAX_TRADES_PER_DAY: int = 5
    MAX_QUANTITY: int = 180
    MAX_ORDER_VALUE: float = 500000.0
    DEFAULT_EXCHANGE: str = "NFO"
    DEFAULT_UNDERLYING: str = "NIFTY"
    JWT_SECRET: str = "change-me-in-production"
    JWT_EXPIRE_MINUTES: int = 60
    BOOTSTRAP_ADMIN_EMAIL: str = ""
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    PAPER_INITIAL_CAPITAL: float = 100000.0
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN: str = "09:15"
    MARKET_CLOSE: str = "15:30"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
