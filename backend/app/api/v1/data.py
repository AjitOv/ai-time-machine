"""Historical-data import API."""

import logging
import re
import time
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Query

from app.engines.data_engine import data_engine
from app.engines.data_importer import import_file

logger = logging.getLogger(__name__)
router = APIRouter()

# Cache pin marker — far-future timestamp so _is_stale never expires it.
_PIN_TTL_SECONDS = 365 * 86400 * 100

# Map filename suffix (in nse 15 min/<NAME>_<suffix>.csv) → canonical timeframe
_TF_FROM_FILENAME = {
    "minute":   "1m",
    "5minute":  "5m",
    "15minute": "15m",
    "30minute": "30m",
    "60minute": "1h",
    "day":      "1d",
}


def _derive_symbol_from_index_name(name: str, exch: str = "NSE") -> str:
    """'NIFTY 50' → 'NSE:NIFTY50-INDEX'; 'INDIA VIX' → 'NSE:INDIAVIX-INDEX'."""
    cleaned = re.sub(r"\s+", "", name).upper()
    return f"{exch}:{cleaned}-INDEX"


def _derive_symbol_from_stock_ticker(ticker: str, exch: str = "NSE") -> str:
    """'RELIANCE' → 'NSE:RELIANCE-EQ'."""
    return f"{exch}:{ticker.upper().strip()}-EQ"


def _parse_15min_filename(filename: str) -> Optional[Tuple[str, str]]:
    """For files like 'NIFTY 50_15minute.csv' return ('NSE:NIFTY50-INDEX','15m').
    Returns None if filename doesn't match the expected pattern."""
    stem = Path(filename).stem  # drop .csv
    # Match <name>_<suffix> at the end
    for suffix, canonical in _TF_FROM_FILENAME.items():
        marker = f"_{suffix}"
        if stem.endswith(marker):
            name = stem[:-len(marker)]
            return _derive_symbol_from_index_name(name), canonical
    return None


@router.post("/import")
async def import_data(
    path: str = Query(..., description="Server-side path to CSV/Parquet/Feather/XLSX file"),
    symbol: str = Query(..., description="Symbol to register the data under, e.g. NSE:NIFTY50-INDEX"),
    timeframe: str = Query(default=None, description="Override; auto-detected from row gaps if omitted"),
    pin: bool = Query(default=True, description="Pin in cache so the periodic TTL refresh doesn't replace it"),
):
    """Load historical OHLCV from a local file into the data_engine cache.

    After import, the existing /backtest/run, /analysis/run, /scanner endpoints
    work transparently on the loaded history — they all read via
    data_engine.get_cached(symbol, timeframe).

    Tolerant of common column conventions (date/time/datetime/timestamp,
    open/o, high/h, low/l, close/c, volume/v/vol; case-insensitive).
    """
    p = Path(path).expanduser()
    if not p.is_absolute():
        # Allow paths relative to the project root for convenience.
        # __file__ is at backend/app/api/v1/data.py — parents[4] is the repo root.
        repo_root = Path(__file__).resolve().parents[4]
        p = (repo_root / path).resolve()

    try:
        df, tf = import_file(p, timeframe)
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.exception("data import failed")
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    cache_key = f"{symbol}_{tf}"
    data_engine._cache[cache_key] = df
    if pin:
        data_engine._cache_ts[cache_key] = time.time() + _PIN_TTL_SECONDS
    else:
        data_engine._cache_ts[cache_key] = time.time()

    logger.info(f"Imported {len(df)} rows for {symbol} {tf} from {p.name}")
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": tf,
        "rows": len(df),
        "start": df.index[0].isoformat(),
        "end": df.index[-1].isoformat(),
        "first_close": round(float(df["close"].iloc[0]), 2),
        "last_close": round(float(df["close"].iloc[-1]), 2),
        "pinned": pin,
        "source": str(p),
    }


@router.post("/import-preset")
async def import_preset(
    preset: str = Query(..., description="nse_15min_indices | nse_index_archive | nse_stock_archive"),
    timeframes: str = Query(default="", description="Comma-separated TFs to include (e.g. '15m,1h,1d'); empty = all"),
    limit: int = Query(default=0, ge=0, le=5000,
                       description="Max files to import (0 = no limit). Useful for trial runs."),
    pin: bool = Query(default=True),
):
    """One-click bulk import for the two NSE archives:

    - **nse_15min_indices**: walks `nse 15 min/` (22 indices × 6 timeframes)
    - **nse_index_archive**: walks `nse data/data_1990_2020/index_data/` (~80 daily indices, 1990-2020)
    - **nse_stock_archive**: walks `nse data/data_1990_2020/stock_data/` (~1640 daily stocks, 1996-2020)

    Each file's (symbol, timeframe) is derived from its filename. Failed files
    are reported in the response but don't abort the batch.
    """
    repo_root = Path(__file__).resolve().parents[4]
    tf_filter = {t.strip() for t in timeframes.split(",") if t.strip()} if timeframes else None

    if preset == "nse_15min_indices":
        folder = repo_root / "nse 15 min"
        derive = _parse_15min_filename
    elif preset == "nse_index_archive":
        folder = repo_root / "nse data" / "data_1990_2020" / "index_data"
        derive = lambda fn: (_derive_symbol_from_index_name(Path(fn).stem), "1d")
    elif preset == "nse_stock_archive":
        folder = repo_root / "nse data" / "data_1990_2020" / "stock_data"
        derive = lambda fn: (_derive_symbol_from_stock_ticker(Path(fn).stem), "1d")
    else:
        return {"ok": False, "error": f"unknown preset '{preset}'"}

    if not folder.exists():
        return {"ok": False, "error": f"folder not found: {folder}"}

    csvs = sorted([p for p in folder.iterdir() if p.suffix.lower() == ".csv"])
    if limit:
        csvs = csvs[:limit]

    imported = []
    skipped = []
    errors = []
    t0 = time.time()

    for fp in csvs:
        try:
            derived = derive(fp.name)
            if derived is None:
                skipped.append({"file": fp.name, "reason": "unrecognised filename"})
                continue
            symbol, tf = derived
            if tf_filter and tf not in tf_filter:
                skipped.append({"file": fp.name, "reason": f"timeframe {tf} filtered out"})
                continue
            df, detected_tf = import_file(fp, tf)
            cache_key = f"{symbol}_{tf}"
            data_engine._cache[cache_key] = df
            data_engine._cache_ts[cache_key] = (time.time() + _PIN_TTL_SECONDS) if pin else time.time()
            imported.append({
                "file": fp.name, "symbol": symbol, "timeframe": tf,
                "rows": len(df),
                "start": df.index[0].isoformat()[:10], "end": df.index[-1].isoformat()[:10],
            })
        except Exception as e:
            errors.append({"file": fp.name, "error": f"{type(e).__name__}: {e}"})

    runtime_ms = int((time.time() - t0) * 1000)
    logger.info(f"preset import '{preset}': {len(imported)} imported, {len(skipped)} skipped, {len(errors)} errors in {runtime_ms}ms")
    return {
        "ok": True,
        "preset": preset,
        "folder": str(folder),
        "scanned": len(csvs),
        "imported_count": len(imported),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "runtime_ms": runtime_ms,
        "imported": imported,
        "skipped": skipped[:50],   # cap for response size
        "errors": errors[:50],
    }


@router.get("/cache")
async def list_cache():
    """List everything currently held in the in-memory candle cache."""
    out = []
    for key, df in data_engine._cache.items():
        if df is None or df.empty:
            continue
        ts = data_engine._cache_ts.get(key, 0)
        pinned = ts > time.time() + 365 * 86400  # pinned cutoff
        out.append({
            "key": key,
            "rows": len(df),
            "start": df.index[0].isoformat(),
            "end": df.index[-1].isoformat(),
            "pinned": pinned,
        })
    return {"count": len(out), "entries": sorted(out, key=lambda x: x["key"])}
