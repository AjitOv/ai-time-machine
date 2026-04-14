"""
Data Engine – ingests market data via yfinance and computes technical indicators.

Handles:
- Historical data download (multi-timeframe)
- Real-time polling
- RSI(14), EMA(11, 21, 50), ATR(14) computation
- Storage in SQLite
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.market_data import MarketData
from app.models.features import Feature

logger = logging.getLogger(__name__)

# yfinance timeframe mapping: our labels → yfinance intervals
TF_MAP = {
    "1m": {"interval": "1m", "period": "7d"},
    "5m": {"interval": "5m", "period": "60d"},
    "15m": {"interval": "15m", "period": "60d"},
    "1h": {"interval": "1h", "period": "730d"},
    "4h": {"interval": "1d", "period": "730d"},  # yfinance doesn't support 4h; approximate from daily
}


class DataEngine:
    """Ingests market data and computes technical indicators."""

    def __init__(self):
        self.symbol = settings.DEFAULT_SYMBOL
        self._cache: Dict[str, pd.DataFrame] = {}

    # ──────────────────────────────────────────────
    # DATA INGESTION
    # ──────────────────────────────────────────────

    def fetch_historical(self, symbol: Optional[str] = None, timeframe: str = "1h") -> pd.DataFrame:
        """Download historical OHLCV data from yfinance."""
        sym = symbol or self.symbol
        tf_config = TF_MAP.get(timeframe, TF_MAP["1h"])

        logger.info(f"Fetching {sym} {timeframe} data (period={tf_config['period']})")
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(
                period=tf_config["period"],
                interval=tf_config["interval"],
                auto_adjust=True,
            )
            if df.empty:
                logger.warning(f"No data returned for {sym} {timeframe}")
                return pd.DataFrame()

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            df.index = df.index.tz_localize(None) if df.index.tz else df.index

            # Cache it
            cache_key = f"{sym}_{timeframe}"
            self._cache[cache_key] = df
            logger.info(f"Fetched {len(df)} candles for {sym} {timeframe}")
            return df

        except Exception as e:
            logger.error(f"Error fetching data for {sym} {timeframe}: {e}")
            return pd.DataFrame()

    def get_cached(self, symbol: Optional[str] = None, timeframe: str = "1h") -> pd.DataFrame:
        """Return cached data or fetch if not available."""
        sym = symbol or self.symbol
        cache_key = f"{sym}_{timeframe}"
        if cache_key not in self._cache or self._cache[cache_key].empty:
            return self.fetch_historical(sym, timeframe)
        return self._cache[cache_key]

    # ──────────────────────────────────────────────
    # TECHNICAL INDICATORS
    # ──────────────────────────────────────────────

    @staticmethod
    def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """Compute Relative Strength Index."""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def compute_ema(series: pd.Series, period: int) -> pd.Series:
        """Compute Exponential Moving Average."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Compute Average True Range."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = true_range.ewm(span=period, adjust=False).mean()
        return atr

    def compute_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all indicators and return enriched DataFrame."""
        if df.empty:
            return df

        result = df.copy()
        result["rsi_14"] = self.compute_rsi(result["close"], settings.RSI_PERIOD)
        for p in settings.EMA_PERIODS:
            result[f"ema_{p}"] = self.compute_ema(result["close"], p)
        result["atr_14"] = self.compute_atr(result, settings.ATR_PERIOD)
        return result

    # ──────────────────────────────────────────────
    # DATABASE OPERATIONS
    # ──────────────────────────────────────────────

    async def store_market_data(self, db: AsyncSession, df: pd.DataFrame,
                                 symbol: str, timeframe: str):
        """Persist OHLCV data to database (upsert-like with skip)."""
        if df.empty:
            return

        stored = 0
        for ts, row in df.iterrows():
            # Check if exists
            existing = await db.execute(
                select(MarketData).where(
                    and_(
                        MarketData.symbol == symbol,
                        MarketData.timeframe == timeframe,
                        MarketData.timestamp == ts.to_pydatetime(),
                    )
                )
            )
            if existing.scalar_one_or_none():
                continue

            record = MarketData(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=ts.to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
            db.add(record)
            stored += 1

        if stored > 0:
            await db.flush()
            logger.info(f"Stored {stored} new candles for {symbol} {timeframe}")

    async def store_features(self, db: AsyncSession, df: pd.DataFrame,
                              symbol: str, timeframe: str):
        """Persist computed features to database."""
        if df.empty:
            return

        stored = 0
        for ts, row in df.iterrows():
            existing = await db.execute(
                select(Feature).where(
                    and_(
                        Feature.symbol == symbol,
                        Feature.timeframe == timeframe,
                        Feature.timestamp == ts.to_pydatetime(),
                    )
                )
            )
            if existing.scalar_one_or_none():
                continue

            record = Feature(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=ts.to_pydatetime(),
                rsi_14=float(row["rsi_14"]) if pd.notna(row.get("rsi_14")) else None,
                ema_11=float(row["ema_11"]) if pd.notna(row.get("ema_11")) else None,
                ema_21=float(row["ema_21"]) if pd.notna(row.get("ema_21")) else None,
                ema_50=float(row["ema_50"]) if pd.notna(row.get("ema_50")) else None,
                atr_14=float(row["atr_14"]) if pd.notna(row.get("atr_14")) else None,
                close=float(row["close"]) if pd.notna(row.get("close")) else None,
                volume=float(row["volume"]) if pd.notna(row.get("volume")) else None,
            )
            db.add(record)
            stored += 1

        if stored > 0:
            await db.flush()
            logger.info(f"Stored {stored} feature records for {symbol} {timeframe}")

    # ──────────────────────────────────────────────
    # FULL PIPELINE
    # ──────────────────────────────────────────────

    async def ingest_and_compute(self, db: AsyncSession, symbol: Optional[str] = None,
                                  timeframes: Optional[List[str]] = None) -> Dict[str, pd.DataFrame]:
        """Full data pipeline: fetch → compute indicators → store."""
        sym = symbol or self.symbol
        tfs = timeframes or settings.SUPPORTED_TIMEFRAMES
        results = {}

        for tf in tfs:
            df = self.fetch_historical(sym, tf)
            if df.empty:
                continue
            enriched = self.compute_all_features(df)
            await self.store_market_data(db, df, sym, tf)
            await self.store_features(db, enriched, sym, tf)
            results[tf] = enriched

        return results

    def get_latest_features(self, symbol: Optional[str] = None, timeframe: str = "1h",
                             lookback: int = 100) -> pd.DataFrame:
        """Get the latest N candles with indicators from cache."""
        df = self.get_cached(symbol, timeframe)
        if df.empty:
            return df
        enriched = self.compute_all_features(df)
        return enriched.tail(lookback)


# Singleton instance
data_engine = DataEngine()
