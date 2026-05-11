"""
Data Engine – ingests market data via yfinance and computes technical indicators.

Handles:
- Historical data download (multi-timeframe)
- Real-time polling
- RSI(14), EMA(11, 21, 50), ATR(14) computation
- Storage in SQLite
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select, and_

# How long a cached frame is allowed to stay before we re-fetch from upstream.
# Tuned per timeframe — finer charts churn faster.
_CACHE_TTL_SECONDS = {
    "1m": 30,
    "5m": 60,
    "15m": 120,
    "1h": 240,
    "4h": 600,
    "1d": 3600,
}
_DEFAULT_TTL = 240

try:
    from growwapi import GrowwAPI
    import pyotp
except ImportError:
    GrowwAPI = None
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.engines.dhan_client import DhanClient
from app.engines.fyers_client import FyersClient
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
        self._cache_ts: Dict[str, float] = {}  # last upstream-fetch timestamp per cache key
        self.dhan = self._init_dhan()
        self.fyers = self._init_fyers()
        self.groww = self._init_groww()

    def _is_stale(self, cache_key: str, timeframe: str) -> bool:
        ts = self._cache_ts.get(cache_key)
        if ts is None:
            return True
        ttl = _CACHE_TTL_SECONDS.get(timeframe, _DEFAULT_TTL)
        return (time.time() - ts) > ttl

    def _init_dhan(self) -> Optional[DhanClient]:
        if not (settings.DHAN_CLIENT_ID and settings.DHAN_ACCESS_TOKEN):
            return None
        # Prefer the legacy local dev location if it exists; otherwise use the
        # canonical bundled location (which DhanClient will auto-populate).
        legacy = Path(__file__).resolve().parents[3] / "data" / "dhan_scrip_master.csv"
        from app.engines.dhan_client import default_scrip_master_path
        scrip_path = legacy if legacy.exists() else default_scrip_master_path()
        logger.info("Dhan client initialized.")
        return DhanClient(
            settings.DHAN_CLIENT_ID,
            settings.DHAN_ACCESS_TOKEN,
            scrip_master_path=scrip_path,
        )

    def _init_fyers(self) -> Optional[FyersClient]:
        if settings.FYERS_APP_ID and settings.FYERS_ACCESS_TOKEN:
            logger.info("FYERS client initialized.")
            return FyersClient(settings.FYERS_APP_ID, settings.FYERS_ACCESS_TOKEN)
        return None

    def _init_groww(self):
        if GrowwAPI and settings.GROWW_API_KEY:
            try:
                if settings.GROWW_TOTP_SECRET:
                    totp_gen = pyotp.TOTP(settings.GROWW_TOTP_SECRET)
                    totp = totp_gen.now()
                    access_token = GrowwAPI.get_access_token(api_key=settings.GROWW_API_KEY, totp=totp)
                    logger.info("Groww API initialized using TOTP flow.")
                    return GrowwAPI(access_token)
                elif settings.GROWW_API_SECRET:
                    access_token = GrowwAPI.get_access_token(api_key=settings.GROWW_API_KEY, secret=settings.GROWW_API_SECRET)
                    logger.info("Groww API initialized using Secret flow.")
                    return GrowwAPI(access_token)
            except Exception as e:
                logger.error(f"Failed to initialize Groww API: {e}")
        return None

    # ──────────────────────────────────────────────
    # DATA INGESTION
    # ──────────────────────────────────────────────

    def fetch_historical(self, symbol: Optional[str] = None, timeframe: str = "1h") -> pd.DataFrame:
        """Download historical OHLCV data. Source priority: Dhan → FYERS → Groww → yfinance."""
        sym = symbol or self.symbol
        is_indian = sym.startswith(("NSE:", "BSE:", "MCX:"))

        cache_key = f"{sym}_{timeframe}"

        # --- PRIMARY: DHAN (NSE/BSE/MCX) ---
        if self.dhan and is_indian:
            df = self.dhan.fetch_candles(sym, timeframe)
            if not df.empty:
                self._cache[cache_key] = df
                self._cache_ts[cache_key] = time.time()
                return df
            logger.warning(f"Dhan returned no data for {sym} {timeframe}. Falling back.")

        # --- SECONDARY: FYERS (NSE/MCX/BSE) ---
        if self.fyers and is_indian:
            df = self.fyers.fetch_candles(sym, timeframe)
            if not df.empty:
                self._cache[cache_key] = df
                self._cache_ts[cache_key] = time.time()
                return df
            logger.warning(f"FYERS returned no data for {sym} {timeframe}. Falling back.")

        # --- SECONDARY: GROWW API ---
        if self.groww:
            try:
                groww_sym = sym.replace(".NS", "").replace(".BO", "")
                end_time_dt = datetime.now()
                
                interval_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
                interval_min = interval_map.get(timeframe, 60)
                
                # Dynamic days back based on timeframe to avoid API limits
                days_back = 30
                if timeframe == "1m": days_back = 5
                elif timeframe in ["5m", "15m"]: days_back = 30
                else: days_back = 100
                
                start_time_dt = end_time_dt - timedelta(days=days_back)
                
                logger.info(f"Fetching {groww_sym} {timeframe} data from Groww API")
                resp = self.groww.get_historical_candle_data(
                    trading_symbol=groww_sym,
                    exchange=self.groww.EXCHANGE_NSE,
                    segment=self.groww.SEGMENT_CASH,
                    start_time=start_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    end_time=end_time_dt.strftime("%Y-%m-%d %H:%M:%S"),
                    interval_in_minutes=interval_min
                )
                
                if resp and 'candles' in resp and len(resp['candles']) > 0:
                    records = resp['candles']
                    df = pd.DataFrame(records, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                    df.set_index('timestamp', inplace=True)

                    self._cache[cache_key] = df
                    self._cache_ts[cache_key] = time.time()
                    logger.info(f"Fetched {len(df)} candles for {sym} {timeframe} via Groww")
                    return df
                else:
                    logger.warning(f"Groww returned empty or invalid data for {sym} {timeframe}. Falling back.")
            except Exception as e:
                logger.error(f"Groww API error for {sym} {timeframe}: {e}. Falling back to yfinance.")

        # --- FALLBACK: YFINANCE ---
        tf_config = TF_MAP.get(timeframe, TF_MAP["1h"])

        logger.info(f"Fetching {sym} {timeframe} data (period={tf_config['period']}) via yfinance")
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(
                period=tf_config["period"],
                interval=tf_config["interval"],
                auto_adjust=True,
            )
            if df.empty:
                logger.warning(f"No data returned for {sym} {timeframe} via yfinance")
                return pd.DataFrame()

            df = df.rename(columns={
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            })
            df = df[["open", "high", "low", "close", "volume"]].copy()
            df.index = pd.to_datetime(df.index)
            df.index = df.index.tz_localize(None) if df.index.tz else df.index

            self._cache[cache_key] = df
            self._cache_ts[cache_key] = time.time()
            logger.info(f"Fetched {len(df)} candles for {sym} {timeframe} via yfinance")
            return df

        except Exception as e:
            logger.error(f"Error fetching data for {sym} {timeframe}: {e}")
            return pd.DataFrame()

    def get_cached(self, symbol: Optional[str] = None, timeframe: str = "1h") -> pd.DataFrame:
        """Return cached data, refreshing from upstream if the cache has aged
        past the per-timeframe TTL or is missing/empty."""
        sym = symbol or self.symbol
        cache_key = f"{sym}_{timeframe}"
        cached = self._cache.get(cache_key)
        if cached is None or cached.empty or self._is_stale(cache_key, timeframe):
            return self.fetch_historical(sym, timeframe)
        return cached

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
