"""
Configuration management for the AI Time Machine system.
Uses pydantic-settings for environment variable validation.
"""

import os
from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings with sensible defaults."""

    # Application
    APP_NAME: str = "AI Time Machine"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'data', 'timemachine.db')}"

    # Market Data
    DEFAULT_SYMBOL: str = "NSE:NIFTY50-INDEX"
    SUPPORTED_TIMEFRAMES: List[str] = ["1m", "5m", "15m", "1h", "4h"]
    DATA_POLL_INTERVAL_SECONDS: int = 60

    # Dhan API (primary source for Indian markets)
    # Get credentials at https://web.dhan.co — generate access token from the
    # DhanHQ developer console. Access tokens are valid for ~24 hours.
    DHAN_CLIENT_ID: Optional[str] = None
    DHAN_ACCESS_TOKEN: Optional[str] = None

    # FYERS API Integration (secondary fallback for Indian markets)
    # Get credentials at https://myapi.fyers.in — app_id + access_token from the
    # OAuth authcode flow. Access tokens expire daily (~08:00 IST).
    FYERS_APP_ID: Optional[str] = None
    FYERS_ACCESS_TOKEN: Optional[str] = None

    # Groww API Integration (fallback for Indian markets)
    GROWW_API_KEY: Optional[str] = None
    GROWW_API_SECRET: Optional[str] = None
    GROWW_TOTP_SECRET: Optional[str] = None

    # Indicators
    RSI_PERIOD: int = 14
    EMA_PERIODS: List[int] = [11, 21, 50]
    ATR_PERIOD: int = 14

    # Monte Carlo
    MC_NUM_SIMULATIONS: int = 100
    MC_FORECAST_STEPS: int = 50

    # Decision Engine
    CONTEXT_WEIGHT: float = 0.25
    BEHAVIOR_WEIGHT: float = 0.25
    DNA_WEIGHT: float = 0.25
    SIMULATION_WEIGHT: float = 0.25

    # Thresholds
    DNA_CONFIDENCE_THRESHOLD: float = 0.6
    SIMULATION_PROBABILITY_THRESHOLD: float = 0.60
    UNCERTAINTY_MAX_THRESHOLD: float = 0.4
    MIN_RISK_REWARD: float = 2.0

    # Risk Management
    MAX_DAILY_RISK_PCT: float = 2.0
    MAX_CONSECUTIVE_LOSSES: int = 3
    BASE_POSITION_SIZE_PCT: float = 1.0

    # Learning
    LEARNING_RATE: float = 0.01
    DNA_DECAY_RATE: float = 0.05
    MIN_DNA_SAMPLE_SIZE: int = 5

    # Alerts (optional — leave blank to disable)
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    ALERT_WEBHOOK_URL: Optional[str] = None
    ALERT_DEDUP_SECONDS: int = 1800  # 30 min: don't re-fire same (sym, tf, dir)

    # Auto-running paper-trading loop
    PAPER_LOOP_ENABLED: bool = False
    PAPER_LOOP_SCAN_INTERVAL_SECONDS: int = 600     # 10 min between full watchlist scans
    PAPER_LOOP_RESOLVE_INTERVAL_SECONDS: int = 180  # 3 min between SL/TP resolutions
    PAPER_LOOP_TIMEFRAMES: List[str] = ["1h"]
    PAPER_LOOP_RESPECT_MARKET_HOURS: bool = True    # only scan 09:15-15:30 IST Mon-Fri
    PAPER_LOOP_TIMEOUT_HOURS: int = 48              # close stale PENDING positions
    PAPER_LOOP_WATCHLIST: Optional[str] = None      # comma-separated; empty → indices+nifty50

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
