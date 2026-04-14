"""Pydantic schemas for market data endpoints."""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


class CandleData(BaseModel):
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class FeatureData(BaseModel):
    timestamp: str
    close: Optional[float] = None
    rsi_14: Optional[float] = None
    ema_11: Optional[float] = None
    ema_21: Optional[float] = None
    ema_50: Optional[float] = None
    atr_14: Optional[float] = None


class MarketDataResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: List[CandleData]
    features: List[FeatureData]
    last_updated: str


class HistoryRequest(BaseModel):
    symbol: Optional[str] = None
    timeframe: str = "1h"
    limit: int = 100
