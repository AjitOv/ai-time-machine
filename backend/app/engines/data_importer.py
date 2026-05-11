"""
Historical-data importer.

Loads a CSV/Parquet/Feather file of OHLCV candles, normalises the column
names regardless of the source's naming convention, parses timestamps to a
naive (UTC-stripped) DatetimeIndex, and returns a clean DataFrame ready for
the engine stack.

Tolerant of common NSE bhav-copy / Yahoo / yfinance / TradingView export
formats — see _COL_ALIASES below.
"""

import logging
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# Case-insensitive matching against these aliases. First match wins.
_COL_ALIASES = {
    "timestamp": [
        "timestamp", "datetime", "date_time", "date time", "date",
        "time", "trade_date", "tradingday",
    ],
    "open":   ["open", "o", "open_price", "openprice"],
    "high":   ["high", "h", "high_price", "highprice"],
    "low":    ["low", "l", "low_price", "lowprice"],
    "close":  ["close", "c", "close_price", "closeprice", "adj close", "adj_close", "adjclose"],
    "volume": ["volume", "v", "vol", "volume_traded", "tradedvolume", "qty"],
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    lc_map = {c.lower().strip(): c for c in df.columns}
    rename_map = {}
    for canonical, aliases in _COL_ALIASES.items():
        for alias in aliases:
            if alias.lower() in lc_map:
                rename_map[lc_map[alias.lower()]] = canonical
                break
    df = df.rename(columns=rename_map)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Required OHLC columns missing: {sorted(missing)}; "
            f"saw {list(df.columns)}"
        )
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df


def _parse_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        return df.sort_index()
    if "timestamp" not in df.columns:
        raise ValueError(
            f"No recognised timestamp column found. "
            f"Columns seen: {list(df.columns)}; "
            f"expected one of {_COL_ALIASES['timestamp']}"
        )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", infer_datetime_format=True)
    bad = df["timestamp"].isna().sum()
    if bad:
        logger.warning(f"Importer: dropped {bad} rows with unparseable timestamps")
        df = df.dropna(subset=["timestamp"])
    df = df.set_index("timestamp").sort_index()
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _detect_timeframe(df: pd.DataFrame) -> str:
    """Infer the candle period from the median gap between consecutive timestamps."""
    if len(df) < 2:
        return "1d"
    diffs = df.index.to_series().diff().dropna()
    median_seconds = int(diffs.dt.total_seconds().median() or 86400)
    candidates = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    nearest = min(candidates.items(), key=lambda kv: abs(kv[1] - median_seconds))[0]
    logger.info(f"Importer: detected timeframe '{nearest}' (median gap = {median_seconds}s)")
    return nearest


def import_file(
    path: Path,
    timeframe_override: Optional[str] = None,
) -> Tuple[pd.DataFrame, str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt", ".tsv"):
        sep = "\t" if suffix == ".tsv" else None  # let pandas sniff for csv
        df = pd.read_csv(path, sep=sep, engine="python")
    elif suffix in (".parquet", ".pq"):
        df = pd.read_parquet(path)
    elif suffix == ".feather":
        df = pd.read_feather(path)
    elif suffix in (".xlsx", ".xls"):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)

    if df.empty:
        raise ValueError(f"File contains no rows: {path}")

    df = _normalise_columns(df)
    df = _parse_timestamp(df)
    df = df[["open", "high", "low", "close", "volume"]]
    # Coerce numeric, drop any junk rows that snuck in
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df["volume"] = df["volume"].fillna(0.0)
    # De-duplicate on timestamp (keep last — usually the corrected row)
    df = df[~df.index.duplicated(keep="last")]

    tf = timeframe_override or _detect_timeframe(df)
    return df, tf
