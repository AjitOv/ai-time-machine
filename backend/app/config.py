"""
Configuration management for the AI Time Machine system.
Uses pydantic-settings for environment variable validation.
"""

import os
from pydantic_settings import BaseSettings
from typing import List


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
    DEFAULT_SYMBOL: str = "SPY"
    SUPPORTED_TIMEFRAMES: List[str] = ["1m", "5m", "15m", "1h", "4h"]
    DATA_POLL_INTERVAL_SECONDS: int = 60

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

    # CORS
    CORS_ORIGINS: List[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
